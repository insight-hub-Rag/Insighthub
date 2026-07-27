

import logging
import time

from app.core.models import RAGResponse
from app.rag.preprocessing.query_preprocessor import QueryPreprocessor
from app.rag.routing.rule_router import RuleRouter
from app.rag.routing.llm_router import LLMRouter
from app.rag.agents.manager import AgentManager
from app.rag.fusion.global_fusion import global_fusion
from app.rag.reranker.cross_encoder import CrossEncoderReranker
from app.rag.generator.generator import Generator

logger = logging.getLogger(__name__)

# Le Rule Router ne renvoie plus que deux cas : None (aucun ID détecté)
# ou confidence=1.0 (ID détecté, 100% fiable). Ce seuil ne sert donc
# plus qu'à documenter l'intention et à rester robuste si le Rule
# Router évolue un jour pour retourner d'autres niveaux de confiance.
RULE_ROUTER_MIN_CONFIDENCE = 0.7


class Orchestrator:

    def __init__(self):
        self.preprocessor = QueryPreprocessor()
        self.rule_router = RuleRouter()
        self.llm_router = LLMRouter()
        self.agent_manager = AgentManager()
        self.reranker = CrossEncoderReranker()
        self.generator = Generator()

    async def ask(
        self,
        question: str,
        user_id: str | None = None,
        forced_sources: list[str] | None = None,
        forced_instance_id: str | None = None,
    ) -> RAGResponse:
        """
        `forced_sources` : utilisé UNIQUEMENT par le chat scopé specifique
        """
        t_start = time.time()

        # 1. Preprocessing
        preprocessed = self.preprocessor.run(question, user_id=user_id)

        # 2. Routage — Rule Router d'abord, LLM Router en repli
        routing = self.rule_router.route(preprocessed)
        if routing is None or routing.confidence < RULE_ROUTER_MIN_CONFIDENCE:
            routing = self.llm_router.route(preprocessed)

        if forced_sources is not None:
            # Chat scopé à une instance : la source est déjà connue à
            # 100% (celle du connecteur testé), pas la peine de laisser
            # le routeur en décider — on garde juste ses filtres/scope.
            routing.sources = forced_sources
            routing.in_scope = True

        if forced_instance_id is not None:
            routing.filters = {**routing.filters, "connector_instance_id": forced_instance_id}

        logger.info(
            f"[Orchestrator] Routage : sources={routing.sources} "
            f"via={routing.router_used} confiance={routing.confidence} "
            f"in_scope={routing.in_scope}"
            + (" (source forcée)" if forced_sources is not None else "")
            + (" (instance forcée)" if forced_instance_id is not None else "")
        )

        # 2bis. Question hors périmètre entreprise — inutile de lancer
        # les agents, la fusion et le reranker pour finir par "je n'ai
        # rien trouvé" : on répond directement, sans source (cohérent :
        # aucune donnée n'a été consultée).
        if not routing.in_scope:
            logger.info(
                "[Orchestrator] Question hors scope → réponse directe, "
                "pipeline RAG sauté"
            )
            return self.generator.generate_out_of_scope(question)

        # 3. Agent Manager — lance les agents des sources choisies en parallèle

        agent_results = await self.agent_manager.run(preprocessed, routing)

        if not agent_results:
            logger.warning("[Orchestrator] Aucun agent n'a retourné de résultat")
            return RAGResponse(
                question=question,
                answer="Je n'ai pas trouvé d'informations pertinentes.",
                sources=[],
                model="none",
                total_chunks_searched=0,
            )

        # 4. Fusion globale — dédup + RRF inter-sources
        fused_chunks = global_fusion(agent_results, top_k=15)

        if not fused_chunks:
            logger.warning("[Orchestrator] Fusion globale vide après filtrage")
            return RAGResponse(
                question=question,
                answer="Je n'ai pas trouvé d'informations pertinentes.",
                sources=[],
                model="none",
                total_chunks_searched=0,
            )

        # 5. Reranking — sauté si TOUS les chunks viennent d'un match exact
        # par identifiant (sql_score=1.0, garanti par search_by_id) :
        # le cross-encoder n'apporte rien pour départager un candidat déjà
        # certain, et peut même donner un score trompeur pour une réponse
        # pourtant correcte à 100%.
        if all(c.sql_score == 1.0 for c in fused_chunks):
            reranked_chunks = fused_chunks[:8]
            logger.info("[Orchestrator] Reranking sauté (match exact par ID)")
        else:
            reranked_chunks = self.reranker.rerank(
                query=preprocessed.cleaned_text,
                chunks=fused_chunks,
                top_n=8,
            )

       
        _SCOPE_ONLY_FILTER_KEYS = {"connector_instance_id", "external_id"}
        real_filters = {
            k: v for k, v in routing.filters.items() if k not in _SCOPE_ONLY_FILTER_KEYS
        }
        response = self.generator.generate(
            question, reranked_chunks,
            filters_were_requested=bool(real_filters),
        )

        total_latency = round((time.time() - t_start) * 1000, 1)
        logger.info(f"[Orchestrator] Pipeline complet en {total_latency}ms")

        return response