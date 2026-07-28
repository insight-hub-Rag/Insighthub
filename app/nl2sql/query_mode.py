"""
app/nl2sql/query_mode.py

Gestion des modes d'exécution NL2SQL :
- Mode Exécution Sandbox/Live : exécute réellement la requête contre la base connectée.
- Mode Aperçu Offline : affiche le SQL généré accompagné de la phrase explicite :
  "Cette requête retournera le résultat une fois la base connectée"
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.nl2sql.query_executor import ExecutionOutcome

logger = logging.getLogger(__name__)

OFFLINE_NOTICE_MESSAGE = "Cette requête retournera le résultat une fois la base connectée"


@dataclass
class QueryModeResult:
    executed: bool
    generated_sql: str
    rows: list[dict[str, Any]]
    row_count: int
    exec_time_ms: float
    message: Optional[str] = None
    error_message: Optional[str] = None


class QueryModeHandler:

    def format_offline_preview(self, generated_sql: str) -> QueryModeResult:
        logger.info("[QueryModeHandler] Mode Aperçu Offline activé — Base non connectée")
        return QueryModeResult(
            executed=False,
            generated_sql=generated_sql,
            rows=[],
            row_count=0,
            exec_time_ms=0.0,
            message=OFFLINE_NOTICE_MESSAGE,
        )

    def handle_execution_outcome(self, generated_sql: str, outcome: ExecutionOutcome) -> QueryModeResult:
        if not outcome.success:
            return QueryModeResult(
                executed=True,
                generated_sql=generated_sql,
                rows=[],
                row_count=0,
                exec_time_ms=outcome.exec_time_ms,
                error_message=outcome.error_message,
            )

        return QueryModeResult(
            executed=True,
            generated_sql=generated_sql,
            rows=outcome.rows,
            row_count=outcome.row_count,
            exec_time_ms=outcome.exec_time_ms,
        )
