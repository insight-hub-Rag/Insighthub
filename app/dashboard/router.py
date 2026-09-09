"""
Dashboard global — vue d'ensemble de la plateforme, réservée aux admins
(D8 : décidé explicitement admin-only, cohérent avec le fait que ce
tableau de bord n'apparaît que dans NAV.admin côté frontend).
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.database import get_db
from app.dashboard.models import (
    DashboardSummary,
    DashboardQuestionsPerDay,
    DashboardConnectorStatusList,
    DashboardRecentQuestionsList,
)
from app.dashboard import repository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    period_days: int = 7,
    db: AsyncSession = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_role("admin")),
) -> DashboardSummary:
    data = await repository.get_summary(db, period_days=period_days)
    return DashboardSummary(**data)


@router.get("/questions-per-day", response_model=DashboardQuestionsPerDay)
async def get_questions_per_day(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_role("admin")),
) -> DashboardQuestionsPerDay:
    data = await repository.questions_per_day(db, days=days)
    return DashboardQuestionsPerDay(days=data)


@router.get("/connector-status", response_model=DashboardConnectorStatusList)
async def get_connector_status(
    db: AsyncSession = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_role("admin")),
) -> DashboardConnectorStatusList:
    data = await repository.connector_status(db)
    return DashboardConnectorStatusList(connectors=data)


@router.get("/recent-questions", response_model=DashboardRecentQuestionsList)
async def get_recent_questions(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_role("admin")),
) -> DashboardRecentQuestionsList:
    data = await repository.recent_questions(db, limit=limit)
    return DashboardRecentQuestionsList(questions=data)