"""
app/reports/usage_analytics/router.py

Endpoints du dashboard "Requêtes & usage" — routage HTTP uniquement,
aucune logique métier ici (déléguée à UsageLogRepository).
"""

import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.reports.usage_analytics.repository import UsageLogRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports/usage-analytics", tags=["usage-analytics"])

_repository = UsageLogRepository()


@router.get("/dashboard", summary="Dashboard Requêtes & usage (KPI + journal)")
async def usage_analytics_dashboard(
    since_days: int = 30,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        stats = await _repository.get_stats(db, since_days=since_days)
        recent = await _repository.get_recent(db, limit=limit)
        return {
            "total_requests": stats.total_requests,
            "avg_latency_ms": stats.avg_latency_ms,
            "top_source": stats.top_source,
            "avg_cost_usd": stats.avg_cost_usd,
            "total_cost_usd": stats.total_cost_usd,
            "queries": recent,
        }
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc