"""
Base commune à tous les agents (Jira, Confluence...).

Orchestre les 3 retrievers (vector, SQL, BM25) pour LE schéma propre à
l'agent, les exécute en parallèle, applique la fusion RRF interne, et
retourne un AgentResult unique avec mesure de latence.

Les retrievers étant synchrones (psycopg2 bloquant), chaque appel est
délégué à un thread via asyncio.to_thread — ça permet quand même la
parallélisation réelle (vector + bm25 + sql en même temps pour CET
agent), et surtout ça ne bloque pas l'event loop pendant que
l'Agent Manager fait tourner plusieurs agents en parallèle.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod

from app.core.models import PreprocessedQuery, RoutingDecision, AgentResult
from app.rag.retrievers.vector_retriever import VectorRetriever, embed_query
from app.rag.retrievers.sql_retriever import SQLRetriever
from app.rag.retrievers.bm25_retriever import BM25Retriever
from app.rag.fusion.rrf import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


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