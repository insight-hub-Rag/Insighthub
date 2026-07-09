"""
Orchestrator — assemble tout le pipeline RAG en une chaîne de fonctions
séquentielle (pas encore LangGraph, volontairement — cf. décision prise
plus tôt : LangGraph sera ajouté à la toute fin, une fois chaque
composant validé isolément).

Flux : Preprocessor → Rule Router → (LLM Router si besoin) →
       Agent Manager → Global Fusion → Reranker → Generator

⚠️ DÉPENDANCE EN ATTENTE : ce fichier importe AgentManager depuis
app/rag/agents/manager.py, qui est encore vide (à la charge du
collègue, avec agents/registry.py, confluence_agent.py, etc.).
Le pipeline ne sera exécutable de bout en bout que quand ces fichiers
seront remplis — normal à ce stade, pas un bug.
"""

import logging
import time

from app.core.models import RAGResponse
from app.rag.preprocessing.query_preprocessor import QueryPreprocessor
from app.rag.routing.rule_router import RuleRouter
from app.rag.routing.llm_router import LLMRouter
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
        self.reranker = CrossEncoderReranker()
        self.generator = Generator()

        # Import différé : évite un crash au démarrage de l'app tant que
        # agents/manager.py et agents/registry.py ne sont pas remplis.
        # Une fois prêts, décommenter la ligne suivante et supprimer le
        # bloc try/except plus bas dans ask().
        # from app.rag.agents.manager import AgentManager
        # self.agent_manager = AgentManager()
        self.agent_manager = None

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
        if self.agent_manager is None:
            logger.error(
                "[Orchestrator] AgentManager non disponible "
                "(agents/manager.py pas encore implémenté)"
            )
            return RAGResponse(
                question=question,
                answer="Le système de recherche n'est pas encore complètement configuré.",
                sources=[],
                model="none",
                total_chunks_searched=0,
            )

        agent_results = await self.agent_manager.run(preprocessed, routing)

        # 4. Fusion globale — dédup + RRF inter-sources
        fused_chunks = global_fusion(agent_results, top_k=15)

        # 5. Reranking — cross-encoder sur les meilleurs candidats
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