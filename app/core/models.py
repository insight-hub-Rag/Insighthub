"""
Modèles de données partagés entre toutes les sources d'ingestion.
Ces dataclasses définissent le "contrat" de données que chaque connecteur
et chaque transformer doivent respecter, quelle que soit la source
(Jira aujourd'hui, ServiceNow / SharePoint demain).
Aucun champ spécifique à une source ne doit apparaître ici (ex: pas de
`jira_issue_type` ou `sn_priority`) — ces détails vont dans `metadata: dict`.
C'est ce qui permet au pipeline de traiter n'importe quelle source de façon
uniforme (Strategy Pattern).
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RawRecord:
    """
    Enregistrement brut tel que récupéré depuis une source, avant toute
    transformation. C'est ce qu'un connecteur produit.
    """
    source_type: str            # 'jira' | 'servicenow' | 'sharepoint'...
    record_id: str               # identifiant natif dans la source (ex: 'PROJ-123')
    raw_data: dict[str, Any]     # payload brut, tel que renvoyé par l'API source


@dataclass
class Chunk:
    """
    Fragment de texte prêt à être vectorisé puis stocké.
    Produit par un transformer à partir d'un RawRecord.
    L'embedding est rempli plus tard, par le pipeline.
    """
    chunk_id: str                # identifiant unique, ex: 'jira-PROJ-123-0'
    document_id: str             # identifiant externe du document parent, ex: 'PROJ-123'
    source_type: str             # 'jira' | 'servicenow'...
    content: str                 # texte à vectoriser
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None   # rempli après l'appel à l'embedder


@dataclass
class SyncResult:
    """
    Résultat retourné par le pipeline après une exécution complète.
    Permet de tracer ce qui s'est passé (succès, volumes, erreurs) et,
    à terme, d'alimenter `sync_history` en base.
    """
    source_type: str
    success: bool = True
    total_fetched: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    error_message: Optional[str] = None


@dataclass
class RAGResponse:
    """Réponse complète du pipeline RAG."""
    question:    str
    answer:      str
    sources:     list
    model:       str
    total_chunks_searched: int


# ==================================================================
# Nouveaux modèles — pipeline orchestrateur (app/rag/)
# Ajoutés pour l'architecture Preprocessor → Router → Agents →
# Fusion → Reranker → Generator. Rien au-dessus n'est modifié.
# ==================================================================

@dataclass
class PreprocessedQuery:
    """
    Question utilisateur nettoyée par le Query Preprocessor.
    Point d'entrée unique consommé par les Routers puis les Agents.
    """
    original_text: str
    cleaned_text: str
    language: str = "fr"
    user_id: Optional[str] = None


@dataclass
class RoutingDecision:
    """
    Décision de routage — produite par le Rule Router OU le LLM Router.
    """
    sources: list[str]                       # ex: ["jira", "servicenow"]
    search_type: str = "hybrid"              # "semantic" | "metadata" | "hybrid"
    filters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    router_used: str = "rule"                # "rule" | "llm"
    reasoning: Optional[str] = None          # utile pour debug / soutenance
    in_scope: bool = True                    # False = question hors périmètre
                                              # entreprise -> l'orchestrateur
                                              # court-circuite tout le pipeline


@dataclass
class RetrievedChunk:
    """
    Un chunk retrouvé par un agent, quelle que soit la méthode
    (SQL / vector / BM25), avec tous les scores intermédiaires
    conservés pour traçabilité (utile en soutenance).
    """
    source_type: str
    document_id: str
    chunk_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Scores par méthode, avant fusion
    sql_score: Optional[float] = None
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None

    # Score après fusion RRF (interne agent, puis global)
    rrf_score: Optional[float] = None

    # Score après reranking (cross-encoder)
    rerank_score: Optional[float] = None


@dataclass
class AgentResult:
    """
    Résultat retourné par un agent spécialisé (JiraAgent, etc.)
    à l'Agent Manager.
    """
    source_type: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    latency_ms: float = 0.0
    error: Optional[str] = None