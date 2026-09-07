"""
Job de scoring HR Analytics — Option B (découplé du pipeline d'ingestion).

Scanne les tickets Jira/ServiceNow fermés qui n'ont pas encore de score
dans reports.ticket_scores, les score via SatisfactionScorer, et
sauvegarde le résultat. Conçu pour être relancé manuellement ou
planifié (cron / tâche périodique) — idempotent : un ticket déjà scoré
n'est jamais retraité tant que PROMPT_VERSION ne change pas.

Usage :
    python -m scripts.score_hr_tickets
"""

import asyncio
import logging

from app.db.database import AsyncSessionLocal
from app.reports.hr_analytics.aggregator import CLOSED_STATUSES
from app.reports.hr_analytics.repository import HrAnalyticsRepository
from app.reports.hr_analytics.satisfaction_scorer import SatisfactionScorer

logger = logging.getLogger(__name__)


async def run() -> None:
    if AsyncSessionLocal is None:
        logger.error("[ScoreHrTickets] Pas de base configurée — arrêt.")
        return

    repo = HrAnalyticsRepository()
    scorer = SatisfactionScorer()

    all_closed_statuses = sorted(
        {s for statuses in CLOSED_STATUSES.values() for s in statuses}
    )

    async with AsyncSessionLocal() as session:
        unscored = await repo.fetch_unscored_closed_tickets(session, all_closed_statuses)
        logger.info(f"[ScoreHrTickets] {len(unscored)} ticket(s) à scorer")

        for ticket in unscored:
            ticket_id = ticket["ticket_id"]
            source_type = ticket["source_type"]
            metadata = ticket["metadata"] or {}

            try:
                content = await repo.fetch_ticket_full_content(
                    session, ticket_id, source_type
                )
                resolution_hours = _compute_resolution_hours(metadata)

                score = scorer.score_ticket(
                    ticket_id=ticket_id,
                    source_type=source_type,
                    title=ticket["title"],
                    content=content,
                    is_closed=True,
                    resolution_hours=resolution_hours,
                )

                assignee = metadata.get("assignee") or metadata.get("assigned_to")
                employee_id = None
                if assignee:
                    employee_id = await repo.get_or_create_employee(session, assignee)

                await repo.upsert_ticket_score(session, {
                    "ticket_id": score.ticket_id,
                    "source_type": score.source_type,
                    "employee_id": employee_id,
                    "is_closed": score.is_closed,
                    "resolution_hours": score.resolution_hours,
                    "complexity_score": score.complexity_score,
                    "satisfaction_score": score.satisfaction_score,
                    "llm_reasoning": score.llm_reasoning,
                    "prompt_version": score.prompt_version,
                })
                await session.commit()
                logger.info(f"[ScoreHrTickets] {ticket_id} ({source_type}) scoré")

            except Exception as e:
                logger.error(f"[ScoreHrTickets] Échec sur {ticket_id} : {e}")
                await session.rollback()


def _compute_resolution_hours(metadata: dict) -> float | None:
    """Calcul pur, pas de dépendance DB — testable isolément."""
    from datetime import datetime

    created_raw = metadata.get("created_at")
    resolved_raw = metadata.get("resolved_at")
    if not created_raw or not resolved_raw:
        return None
    try:
        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        resolved = datetime.fromisoformat(resolved_raw.replace("Z", "+00:00"))
        return round((resolved - created).total_seconds() / 3600, 1)
    except (ValueError, AttributeError):
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())