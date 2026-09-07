"""
Router FastAPI — dashboard "Rapport de productivité RH".

Responsabilité UNIQUE : exposer les endpoints HTTP, valider les
paramètres d'entrée, déléguer tout le travail à HrAnalyticsAggregator.
Aucune logique métier ni SQL ici.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.reports.hr_analytics.aggregator import HrAnalyticsAggregator
from app.reports.hr_analytics.models import DashboardOut

router = APIRouter(prefix="/reports/hr-analytics", tags=["Reports RH"])

_aggregator = HrAnalyticsAggregator()


@router.get("/dashboard", response_model=DashboardOut,
            summary="Rapport de productivité RH — KPIs, productivité par collaborateur, synthèse IA")
async def get_dashboard(
    period_start: Optional[datetime] = Query(
        default=None, description="Début de la période (ISO 8601). Omis = pas de filtre."
    ),
    period_end: Optional[datetime] = Query(
        default=None, description="Fin de la période (ISO 8601). Omis = pas de filtre."
    ),
    session: AsyncSession = Depends(get_db),
) -> DashboardOut:
    return await _aggregator.build_dashboard(
        session, period_start=period_start, period_end=period_end
    )