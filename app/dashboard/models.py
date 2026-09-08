"""
Schémas Pydantic pour le Dashboard global (vue admin — toutes sources,
tous utilisateurs confondus, contrairement au chat personnalisé de
app/db/chat_history.py qui filtre par utilisateur).
"""

from typing import Optional

from pydantic import BaseModel


class DashboardKpi(BaseModel):
    value: float
    trend_pct: Optional[float] = None  # None si pas de donnée sur la période précédente


class DashboardSummary(BaseModel):
    questions_posees: DashboardKpi
    confiance_moyenne: DashboardKpi       # 0-100 (pourcentage)
    documents_indexes: DashboardKpi
    utilisateurs_actifs: DashboardKpi
    period_days: int


class DashboardDayCount(BaseModel):
    date: str    # ISO (AAAA-MM-JJ)
    count: int


class DashboardQuestionsPerDay(BaseModel):
    days: list[DashboardDayCount]


class DashboardConnectorStatus(BaseModel):
    source_type: str
    instance_label: str
    is_enabled: bool
    last_sync_status: Optional[str] = None
    last_sync_at: Optional[str] = None


class DashboardConnectorStatusList(BaseModel):
    connectors: list[DashboardConnectorStatus]


class DashboardRecentQuestion(BaseModel):
    id: str
    user_full_name: str
    question: str
    source_types: list[str]
    confidence_pct: Optional[float] = None
    created_at: Optional[str] = None


class DashboardRecentQuestionsList(BaseModel):
    questions: list[DashboardRecentQuestion]