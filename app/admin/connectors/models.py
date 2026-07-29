from datetime import datetime
from enum import IntEnum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SourceType(str):
    """Pas un Enum strict : de nouvelles sources (ServiceNow...) peuvent
    s'ajouter sans casser l'API existante — juste une contrainte de
    validation côté service.py au moment de la création."""
    JIRA = "jira"
    CONFLUENCE = "confluence"
    SHAREPOINT = "sharepoint"
    SERVICENOW = "servicenow"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ORACLE = "oracle"
    MSSQL = "mssql"
    SQLITE = "sqlite"


class SyncFrequency(IntEnum):
    """Valeurs en minutes — correspond exactement aux boutons de l'UI
    (15 min / 30 min / 1 heure / 6 heures)."""
    FIFTEEN_MIN = 15
    THIRTY_MIN = 30
    ONE_HOUR = 60
    SIX_HOURS = 360


class ConnectorStatus(str):
    """Valeurs possibles du badge affiché dans l'UI — calculées par
    service.py, jamais stockées telles quelles en base."""
    ACTIVE = "active"        # badge vert "Actif"
    ERROR = "error"          # badge rouge "Échec"
    PAUSED = "paused"        # toggle désactivé par l'utilisateur
    PENDING = "pending"      # créé mais jamais encore synchronisé


# ---------------------------------------------------------------------
# Réponses (ce que l'API renvoie au frontend)
# ---------------------------------------------------------------------

class SyncStats(BaseModel):
    total_fetched: int = 0
    total_documents: int = 0
    modified: int = 0
    duration_seconds: float = 0.0


class ConnectorSummary(BaseModel):
    """Pour la liste de gauche (panneau 'Sources actives')."""
    id: UUID
    source_type: str
    instance_label: str
    status: str  # calculé par service.py — voir ConnectorStatus
    last_sync_at: Optional[datetime] = None
    sync_frequency_minutes: int


class ConnectorDetail(BaseModel):
    """Pour le panneau de détail à droite. Ne contient JAMAIS le token
    en clair — auth_masked donne juste de quoi afficher les points
    "••••••••" côté UI, jamais la vraie valeur."""
    id: UUID
    source_type: str
    instance_label: str
    status: str
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None
    last_sync_stats: Optional[SyncStats] = None
    last_error: Optional[str] = None
    sync_scope: dict[str, Any] = Field(default_factory=dict)
    sync_frequency_minutes: int
    auth_fields: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------
# Requêtes (ce que le frontend envoie à l'API)
# ---------------------------------------------------------------------

class ConnectorCreate(BaseModel):
    source_type: str
    instance_label: str
    auth_fields: dict[str, str]
    sync_scope: dict[str, Any] = Field(default_factory=dict)
    sync_frequency_minutes: SyncFrequency = SyncFrequency.FIFTEEN_MIN


class ConnectorUpdate(BaseModel):
    """Tous les champs optionnels — PATCH partiel, on ne modifie que ce
    qui est fourni."""
    instance_label: Optional[str] = None
    auth_fields: Optional[dict[str, str]] = None
    sync_scope: Optional[dict[str, Any]] = None
    sync_frequency_minutes: Optional[SyncFrequency] = None


class ConnectorCatalogItem(BaseModel):
    """Pour la modale 'Ajouter une source'."""
    source_type: str
    display_name: str
    description: str
    required_auth_fields: list[str]


class ChatHistoryItem(BaseModel):
    """Un message précédent envoyé au chat scopé."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class DumpTableSummary(BaseModel):
    id: str
    name: str
    columns: list[str]
    accessible: bool = True


class DumpUploadResponse(BaseModel):
    status: str
    connection_id: str
    engine_dialect: str
    database_name: str
    tables: list[DumpTableSummary]
