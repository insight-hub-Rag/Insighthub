"""
app/reports/usage_analytics/repository.py

Persiste et lit le journal des requêtes (coût LLM par requête) —
alimente le dashboard "Requêtes & usage". SQL pur via text(), même
style que app/nl2sql/query_logger.py.

Écriture "best effort" : si la persistance du log échoue, ça ne doit
JAMAIS faire échouer la réponse déjà envoyée à l'utilisateur — le
logging est une préoccupation secondaire par rapport à la réponse
elle-même (même principe que QueryLogger).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.reports.usage_analytics.models import RequestLogEntry, UsageStats

logger = logging.getLogger(__name__)


class UsageLogRepository:

    async def log(self, session: AsyncSession, entry: RequestLogEntry) -> None:
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO reports.request_logs
                        (question, source, latency_ms, model,
                         input_tokens, output_tokens, cost_usd)
                    VALUES
                        (:question, :source, :latency_ms, :model,
                         :input_tokens, :output_tokens, :cost_usd)
                    """
                ),
                {
                    "question": entry.question,
                    "source": entry.source,
                    "latency_ms": entry.latency_ms,
                    "model": entry.model,
                    "input_tokens": entry.input_tokens,
                    "output_tokens": entry.output_tokens,
                    "cost_usd": entry.cost_usd,
                },
            )
            await session.commit()
            logger.info(
                f"[UsageLogRepository] Log enregistré — source='{entry.source}' "
                f"cost_usd={entry.cost_usd}"
            )
        except Exception as exc:
            await session.rollback()
            logger.error(f"[UsageLogRepository] Échec de persistance du log : {exc}")

    async def get_stats(self, session: AsyncSession, since_days: int = 30) -> UsageStats:
        """
        Une seule requête atomique (au lieu de deux round-trips
        séparés) : le total et la source majoritaire viennent de la
        MÊME lecture de la table, avec le même filtre WHERE — évite
        toute divergence entre les deux résultats.
        """
        result = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                    COALESCE(AVG(cost_usd), 0) AS avg_cost_usd,
                    COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                    (
                        SELECT source
                        FROM reports.request_logs
                        WHERE created_at >= NOW() - make_interval(days => :since_days)
                        GROUP BY source
                        ORDER BY COUNT(*) DESC
                        LIMIT 1
                    ) AS top_source
                FROM reports.request_logs
                WHERE created_at >= NOW() - make_interval(days => :since_days)
                """
            ),
            {"since_days": since_days},
        )
        row = result.mappings().first()

        return UsageStats(
            total_requests=row["total_requests"] or 0,
            avg_latency_ms=round(float(row["avg_latency_ms"]), 1),
            top_source=row["top_source"] if row["top_source"] else "—",
            avg_cost_usd=round(float(row["avg_cost_usd"]), 6),
            total_cost_usd=round(float(row["total_cost_usd"]), 6),
        )

    async def get_recent(self, session: AsyncSession, limit: int = 50) -> list[dict]:
        result = await session.execute(
            text(
                """
                SELECT id, question, source, latency_ms, model,
                       input_tokens, output_tokens, cost_usd, created_at
                FROM reports.request_logs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        # cost_usd est NUMERIC en base -> decimal.Decimal côté asyncpg,
        # jamais un float natif. Cast explicite ici pour garantir un
        # JSON numérique côté front (Decimal non casté peut sérialiser
        # en string selon l'encodeur JSON utilisé).
        rows = []
        for row in result.mappings().all():
            entry = dict(row)
            entry["cost_usd"] = float(entry["cost_usd"])
            rows.append(entry)
        return rows