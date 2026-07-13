"""
app/nl2sql/query_logger.py

Persiste chaque exécution de requête NL2SQL — alimente directement le
dashboard SQL Monitoring (cartes de stats + tableau "Recent generated
queries" vus dans la maquette).

Même style que schema_store.py : AsyncSession injectée (base
InsightHub), raw SQL via text(), pas d'ORM déclaratif. Table dédiée :
nl2sql_query_execution_logs.

Écriture "best effort" : si la persistance du log échoue, ça ne doit
JAMAIS faire échouer la réponse déjà obtenue pour l'utilisateur — le
logging est une préoccupation secondaire par rapport à la réponse
elle-même.

Note driver : asyncpg (contrairement à psycopg2) exige un véritable
objet datetime pour une colonne TIMESTAMPTZ — une str ISO lève une
DataError silencieusement avalée par le try/except best-effort. D'où
la conversion explicite str -> datetime avant insertion (même
correction que schema_store.py).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.nl2sql.models import QueryExecutionLog

logger = logging.getLogger(__name__)


class QueryLogger:

    async def log(self, session: AsyncSession, entry: QueryExecutionLog) -> None:
        created_at = self._parse_created_at(entry.created_at)

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO nl2sql_query_execution_logs
                        (connection_id, natural_language_question, generated_sql,
                         engine_dialect, source_label, status, exec_time_ms,
                         suggested_improvement, error_message, created_at)
                    VALUES
                        (:connection_id, :natural_language_question, :generated_sql,
                         :engine_dialect, :source_label, :status, :exec_time_ms,
                         :suggested_improvement, :error_message, :created_at)
                    """
                ),
                {
                    "connection_id": entry.connection_id,
                    "natural_language_question": entry.natural_language_question,
                    "generated_sql": entry.generated_sql,
                    "engine_dialect": entry.engine_dialect,
                    "source_label": entry.source_label,
                    "status": entry.status,
                    "exec_time_ms": entry.exec_time_ms,
                    "suggested_improvement": entry.suggested_improvement,
                    "error_message": entry.error_message,
                    "created_at": created_at,
                },
            )
            await session.commit()
            logger.info(
                f"[QueryLogger] Log enregistré — status='{entry.status}' "
                f"exec_time={entry.exec_time_ms}ms"
            )
        except Exception as exc:
            await session.rollback()
            logger.error(f"[QueryLogger] Échec de persistance du log : {exc}")

    @staticmethod
    def _parse_created_at(created_at: str | None) -> datetime:
        """Convertit le str ISO du modèle métier en datetime réel,
        requis par asyncpg pour une colonne TIMESTAMPTZ."""
        if created_at:
            try:
                return datetime.fromisoformat(created_at)
            except ValueError:
                logger.warning(
                    f"[QueryLogger] created_at invalide ('{created_at}'), "
                    f"utilisation de l'heure courante."
                )
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------
    # Lecture — utilisée par les endpoints de monitoring
    # ------------------------------------------------------------

    async def get_recent(
        self, session: AsyncSession, limit: int = 50
    ) -> list[dict]:
        result = await session.execute(
            text(
                """
                SELECT connection_id, natural_language_question, generated_sql,
                       engine_dialect, source_label, status, exec_time_ms,
                       suggested_improvement, error_message, created_at
                FROM nl2sql_query_execution_logs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_stats(self, session: AsyncSession, since_days: int = 30) -> dict:
        """Alimente les 4 cartes du haut du dashboard : total généré,
        % accepted / optimized / rejected sur la période.

        Note : l'intervalle est construit via make_interval(days => ...)
        plutôt qu'une concaténation ('N days')::interval, car asyncpg
        est strict sur les types de paramètres — il refuse de faire
        || entre un int et un text sans cast explicite côté requête."""
        result = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
                    COUNT(*) FILTER (WHERE status = 'optimized') AS optimized,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected
                FROM nl2sql_query_execution_logs
                WHERE created_at >= NOW() - make_interval(days => :since_days)
                """
            ),
            {"since_days": since_days},
        )
        row = result.mappings().first()
        total = row["total"] or 0

        return {
            "total_generated": total,
            "accepted_pct": round((row["accepted"] / total * 100), 0) if total else 0,
            "optimized_pct": round((row["optimized"] / total * 100), 0) if total else 0,
            "rejected_pct": round((row["rejected"] / total * 100), 0) if total else 0,
        }