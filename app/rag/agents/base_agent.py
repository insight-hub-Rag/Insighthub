"""
Base commune à tous les agents (Jira, Confluence...).

Orchestre les 3 retrievers (vector, SQL, BM25) pour LE schéma propre à
l'agent, les exécute en parallèle, applique la fusion RRF interne, et
retourne un AgentResult unique avec mesure de latence.

Cas particulier : si le router a détecté un identifiant exact (ex:
"IH-1"), on court-circuite toute la recherche floue et on va chercher
CE document précisément via search_by_id() — inutile de lancer
vector/BM25/metadata quand on sait déjà exactement quel document on veut.

Les retrievers étant synchrones (psycopg2 bloquant), chaque appel est
délégué à un thread via asyncio.to_thread — ça permet quand même la
parallélisation réelle (vector + bm25 + sql en même temps pour CET
agent), et surtout ça ne bloque pas l'event loop pendant que
l'Agent Manager fait tourner plusieurs agents en parallèle.
"""

import asyncio
import logging
import time
from abc import ABC

from app.core.models import PreprocessedQuery, RoutingDecision, AgentResult, RetrievedChunk
from app.rag.retrievers.vector_retriever import VectorRetriever, embed_query
from app.rag.retrievers.sql_retriever import SQLRetriever, ALLOWED_FILTER_KEYS
from app.rag.retrievers.bm25_retriever import BM25Retriever
from app.rag.fusion.rrf import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def _matches_filters(chunk: RetrievedChunk, filters: dict) -> bool:
    """
    Vérifie qu'un chunk déjà fusionné (vector + bm25 + sql confondus)
    correspond VRAIMENT à un filtre exact (status="In Progress"...),
    plutôt que de se contenter du boost RRF qui le laissait remonter
    sans jamais exclure les chunks non conformes.

    Chaque valeur de `filters` peut être une chaîne unique OU une liste
    de valeurs candidates (ex: ["Highest", "High"]) — le chunk matche
    si AU MOINS UNE valeur correspond.

    Clé suffixée "_not" (ex: "status_not": "Terminé") = négation VRAIE,
    pas une énumération à deviner. Demander au LLM de lister "toutes les
    valeurs sauf Terminé" est fragile : il peut en oublier une (vécu en
    pratique — "En cours" manquant sur "non résolus"). "status_not"
    exclut la valeur précisément, quel que soit le nombre de valeurs
    possibles dans l'énumération, sans avoir besoin de toutes les
    connaître à l'avance.
    """
    for key, expected in filters.items():
        is_negation = key.endswith("_not")
        base_key = key[: -len("_not")] if is_negation else key
        chunk_value = str((chunk.metadata or {}).get(base_key, "")).lower()
        candidates = expected if isinstance(expected, list) else [expected]
        any_match = any(str(v).lower() in chunk_value for v in candidates)
        if is_negation:
            if any_match:
                return False
        else:
            if not any_match:
                return False
    return True


class BaseAgent(ABC):
    """
    Classe abstraite : un agent concret (JiraAgent, ConfluenceAgent...)
    n'a besoin de définir QUE `source_type` (le nom du schéma SQL).
    Tout le reste — orchestration, parallélisme, fusion — est hérité.
    """

    source_type: str  # défini par chaque sous-classe, ex: "jira"

    def __init__(self, top_k_per_method: int = 20, top_k_final: int = 10):
        self.vector_retriever = VectorRetriever()
        self.sql_retriever = SQLRetriever()
        self.bm25_retriever = BM25Retriever()
        self.top_k_per_method = top_k_per_method
        self.top_k_final = top_k_final

    async def run(
        self,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> AgentResult:
        t0 = time.time()

        try:
            # Court-circuit : identifiant exact détecté par le Rule Router
            # (ex: "IH-1") → recherche directe, pas de recherche floue.
            external_id = routing.filters.get("external_id")
            if external_id:
                chunks = await asyncio.to_thread(
                    self.sql_retriever.search_by_id,
                    schema=self.source_type,
                    external_id=external_id,
                )
                latency_ms = round((time.time() - t0) * 1000, 1)
                logger.info(
                    f"[{self.source_type}Agent] Recherche directe par ID "
                    f"'{external_id}' | {len(chunks)} chunks | {latency_ms}ms"
                )
                return AgentResult(
                    source_type=self.source_type,
                    chunks=chunks,
                    latency_ms=latency_ms,
                )

            # Embedding calculé une seule fois, réutilisé par le vector retriever
            query_embedding = await asyncio.to_thread(
                embed_query, query.cleaned_text
            )

            tasks = [
                asyncio.to_thread(
                    self.vector_retriever.search,
                    schema=self.source_type,
                    query_text=query.cleaned_text,
                    top_k=self.top_k_per_method,
                    query_embedding=query_embedding,
                ),
                asyncio.to_thread(
                    self.bm25_retriever.search,
                    schema=self.source_type,
                    query_text=query.cleaned_text,
                    top_k=self.top_k_per_method,
                ),
            ]

            # SQL metadata search seulement si le router a extrait des filtres
            # (autres que external_id, déjà géré au-dessus)
            if routing.filters:
                tasks.append(
                    asyncio.to_thread(
                        self.sql_retriever.search,
                        schema=self.source_type,
                        filters=routing.filters,
                        top_k=self.top_k_per_method,
                    )
                )

            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            ranked_lists = []
            for result in raw_results:
                if isinstance(result, Exception):
                    logger.warning(
                        f"[{self.source_type}Agent] un retriever a échoué : {result}"
                    )
                    continue
                if result:
                    ranked_lists.append(result)

            fused = reciprocal_rank_fusion(ranked_lists) if ranked_lists else []

            # Filtrage STRICT post-fusion : le filtre extrait par le
            # routeur (status, priority...) ne doit plus seulement
            # "booster" un chunk via RRF — sinon "les tickets en cours"
            # renvoie quand même tous les tickets, juste réordonnés. On
            # exclut ici tout chunk qui ne correspond pas vraiment,
            # quelle que soit la méthode qui l'a trouvé (vector/bm25/sql).
            allowed_keys = ALLOWED_FILTER_KEYS.get(self.source_type, set())
            hard_filters = {
                k: v for k, v in routing.filters.items()
                if v and (k.removesuffix("_not") in allowed_keys)
            }
            if hard_filters:
                before = len(fused)
                fused = [c for c in fused if _matches_filters(c, hard_filters)]
                logger.info(
                    f"[{self.source_type}Agent] Filtre strict {hard_filters} : "
                    f"{before} -> {len(fused)} chunks"
                )

            top_chunks = fused[: self.top_k_final]

            latency_ms = round((time.time() - t0) * 1000, 1)
            logger.info(
                f"[{self.source_type}Agent] {len(top_chunks)} chunks retenus | "
                f"{latency_ms}ms"
            )

            return AgentResult(
                source_type=self.source_type,
                chunks=top_chunks,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            logger.error(f"[{self.source_type}Agent] erreur : {e}")
            return AgentResult(
                source_type=self.source_type,
                chunks=[],
                latency_ms=latency_ms,
                error=str(e),
            )