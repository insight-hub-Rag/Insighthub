"""
Interfaces communes du pipeline RAG.

Ce fichier ne contient AUCUNE logique métier — uniquement des contrats
abstraits (Protocol) que chaque composant concret doit respecter.
Le reste du pipeline (orchestrator, manager...) dépend de ces interfaces,
jamais des implémentations concrètes (Jira, Confluence...).

C'est ce qui permet le principe Open/Closed : ajouter une nouvelle source
ou changer d'algorithme de reranking ne nécessite de modifier aucun fichier
existant, seulement d'ajouter une nouvelle implémentation de ces contrats.
"""

from typing import Optional, Protocol, runtime_checkable

from app.core.models import (
    PreprocessedQuery,
    RoutingDecision,
    RetrievedChunk,
    AgentResult,
    RAGResponse,
)


@runtime_checkable
class BaseRetriever(Protocol):
    """
    Contrat pour une méthode de recherche brute (vector, sql, bm25).
    Chaque retriever cherche dans UN schéma donné et retourne une liste
    de chunks, sans connaître le contexte plus large (agent, fusion...).
    """

    def search(
        self,
        schema: str,
        query_text: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        ...


@runtime_checkable
class BaseAgent(Protocol):
    """
    Contrat pour un agent spécialisé par source (Jira, Confluence...).
    Un agent orchestre plusieurs retrievers pour SON schéma, applique
    la fusion RRF interne, et retourne un résultat unique et complet.
    """

    source_type: str  # "jira", "confluence", "sharepoint"...

    async def run(
        self,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> AgentResult:
        ...


@runtime_checkable
class BaseRouter(Protocol):
    """
    Contrat pour un router (Rule Router ou LLM Router).
    Décide quelles sources interroger et avec quelle stratégie.
    """

    def route(self, query: PreprocessedQuery) -> Optional[RoutingDecision]:
        """Retourne None si ce router ne sait pas trancher (ex: Rule
        Router face à une question ambiguë) — signale qu'il faut passer
        au router suivant dans la chaîne."""
        ...


@runtime_checkable
class BaseGenerator(Protocol):
    """
    Contrat pour la génération finale de la réponse.
    """

    async def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
    ) -> RAGResponse:
        ...