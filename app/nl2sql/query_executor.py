"""
app/nl2sql/query_executor.py

Exécute une requête SQL déjà validée READ-ONLY contre la base cible,
mesure sa latence d'exécution, et gère le timeout.

IMPORTANT : ce module suppose que la requête a déjà été validée par
query_validator.py — il n'effectue AUCUNE vérification de sécurité
lui-même (SRP strict). Ne jamais appeler execute() sur une requête non
validée en amont.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EXECUTION_TIMEOUT_SECONDS = 1
MAX_ROWS_RETURNED = 500


@dataclass
class ExecutionOutcome:
    success: bool
    rows: list[dict[str, Any]]
    row_count: int
    exec_time_ms: float
    error_message: Optional[str] = None
    truncated: bool = False
    offline_preview: bool = False
    message: Optional[str] = None


class QueryExecutor:

    def execute(self, session: Optional[Session], sql: str, dialect: str) -> ExecutionOutcome:
        if session is None:
            from app.nl2sql.query_mode import OFFLINE_NOTICE_MESSAGE
            logger.info("[QueryExecutor] Aucune session active — mode aperçu sans exécution DB.")
            return ExecutionOutcome(
                success=True,
                rows=[],
                row_count=0,
                exec_time_ms=0.0,
                offline_preview=True,
                message=OFFLINE_NOTICE_MESSAGE,
            )

        self._apply_statement_timeout(session, dialect)

        started_at = time.perf_counter()
        try:
            result = session.execute(text(sql))
            columns = list(result.keys())
            raw_rows = result.fetchmany(MAX_ROWS_RETURNED + 1)

            truncated = len(raw_rows) > MAX_ROWS_RETURNED
            raw_rows = raw_rows[:MAX_ROWS_RETURNED]

            rows = [dict(zip(columns, row)) for row in raw_rows]
            exec_time_ms = (time.perf_counter() - started_at) * 1000

            logger.info(
                f"[QueryExecutor] OK — {len(rows)} ligne(s) en {exec_time_ms:.1f}ms"
                + (" (tronqué)" if truncated else "")
            )
            return ExecutionOutcome(
                success=True,
                rows=rows,
                row_count=len(rows),
                exec_time_ms=exec_time_ms,
                truncated=truncated,
            )

        except SQLAlchemyError as exc:
            exec_time_ms = (time.perf_counter() - started_at) * 1000
            logger.error(f"[QueryExecutor] Échec après {exec_time_ms:.1f}ms : {exc}")
            return ExecutionOutcome(
                success=False,
                rows=[],
                row_count=0,
                exec_time_ms=exec_time_ms,
                error_message=self._clean_error(exc),
            )
        finally:
            session.rollback()

    def _apply_statement_timeout(self, session: Session, dialect: str) -> None:
        timeout_ms = int(EXECUTION_TIMEOUT_SECONDS * 1000)
        try:
            if dialect == "postgresql":
                session.execute(text(f"SET statement_timeout = {timeout_ms}"))
            elif dialect == "mysql":
                session.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
        except SQLAlchemyError:
            logger.warning(
                f"[QueryExecutor] Impossible de positionner statement_timeout "
                f"pour dialect='{dialect}'"
            )

    @staticmethod
    def _clean_error(exc: SQLAlchemyError) -> str:
        message = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
        return message.splitlines()[0][:300]