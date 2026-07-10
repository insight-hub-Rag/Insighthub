"""
Orchestrator — assemble tout le pipeline RAG en une chaîne de fonctions
séquentielle (pas encore LangGraph, volontairement — LangGraph sera
ajouté à la toute fin, une fois chaque composant validé isolément).

Flux : Preprocessor → Rule Router → (LLM Router si besoin) →
       Agent Manager → Global Fusion → Reranker (sauf match ID exact) →
       Generator
"""

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

# Seuil de confiance en dessous duquel une décision du Rule Router
# est considérée trop incertaine — on passe alors au LLM Router.
RULE_ROUTER_MIN_CONFIDENCE = 0.7


class Orchestrator:

    def __init__(self):
        self.preprocessor = QueryPreprocessor()
        self.rule_router = RuleRouter()
        self.llm_router = LLMRouter()
        self.agent_manager = AgentManager()
        self.reranker = CrossEncoderReranker()
        self.generator = Generator()

    async def ask(self, question: str, user_id: str | None = None) -> RAGResponse:
        t_start = time.time()

        # 1. Preprocessing
        preprocessed = self.preprocessor.run(question, user_id=user_id)

        # 2. Routage — Rule Router d'abord, LLM Router en repli
        routing = self.rule_router.route(preprocessed)
        if routing is None or routing.confidence < RULE_ROUTER_MIN_CONFIDENCE:
            routing = self.llm_router.route(preprocessed)

        logger.info(
            f"[Orchestrator] Routage : sources={routing.sources} "
            f"via={routing.router_used} confiance={routing.confidence}"
        )

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

        # 6. Génération finale (le Context Builder est appelé à l'intérieur)
        response = self.generator.generate(question, reranked_chunks)

        total_latency = round((time.time() - t_start) * 1000, 1)
        logger.info(f"[Orchestrator] Pipeline complet en {total_latency}ms")

        return response