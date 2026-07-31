"""
app/nl2sql/orchestrator.py

NL2SQLAgent — point d'entrée du module, appelable par l'AgentManager
exactement comme JiraAgent/ConfluenceAgent/SharePointAgent, MAIS sans
hériter de BaseAgent (le pipeline est totalement différent : pas de
vector/BM25/RRF). Respecte uniquement le contrat duck-typed défini par
le Protocol BaseAgent dans app/rag/interfaces.py :
  - attribut source_type: str
  - async def run(query, routing) -> AgentResult

CORRECTIF FINAL : cette version n'exécute plus JAMAIS de SQL contre une
vraie base cible. Phase actuelle du projet = dump schema-only (sans
données, sans connexion persistante — sandbox détruit après scan). Le
pipeline utilise uniquement le schéma déjà scanné et stocké dans la
base interne InsightHub (schema_store), résolu dynamiquement depuis le
connecteur SQL actuellement actif (is_enabled=True) plutôt qu'un
connection_id figé "default". Pour chaque question :
  - le SQL est généré à partir du schéma stocké
  - la réponse retournée est TOUJOURS le SQL généré + un message
    explicite indiquant qu'un résultat réel nécessite une base
    connectée (cf. décision validée : Type 2 = SQL + notice, pas
    d'exécution simulée).
"""

import asyncio
import logging
import time

from app.admin.connectors.repository import ConnectorRepository
from app.core.models import AgentResult, PreprocessedQuery, RetrievedChunk, RoutingDecision
from app.db.database import AsyncSessionLocal
from app.nl2sql.models import NL2SQLConfig, QueryExecutionLog, SchemaScanResult
from app.nl2sql.query_generator import QueryGenerator
from app.nl2sql.query_logger import QueryLogger
from app.nl2sql.query_optimizer import QueryOptimizer
from app.nl2sql.query_validator import QueryValidator
from app.nl2sql.response_formatter import ResponseFormatter
from app.nl2sql.schema_cache import SchemaCache
from app.nl2sql.schema_store import SchemaStore

logger = logging.getLogger(__name__)

_PREVIEW_NOTICE = "Cette requête retournera le résultat une fois la base connectée."


class NL2SQLAgent:

    source_type = "sql"   # requis par le contrat duck-typed de interfaces.py

    def __init__(
        self,
        config: NL2SQLConfig,
        schema_cache: SchemaCache,
        query_generator: QueryGenerator,
        query_optimizer: QueryOptimizer,
        response_formatter: ResponseFormatter,
        connector_repository: ConnectorRepository | None = None,
    ):
        self._config = config
        self._schema_cache = schema_cache
        self._schema_store = SchemaStore()
        self._query_generator = query_generator
        self._query_validator = QueryValidator()
        self._query_optimizer = query_optimizer
        self._response_formatter = response_formatter
        self._query_logger = QueryLogger()
        self._connector_repo = connector_repository or ConnectorRepository()

    async def run(
        self,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> AgentResult:
        started_at = time.perf_counter()

        try:
            async with AsyncSessionLocal() as db_session:
                # Résolution dynamique de la base active — plus jamais
                # de connection_id figé.
                active_connector = await self._connector_repo.get_active_sql_connector(
                    db_session
                )

                if active_connector is None:
                    return self._no_active_database_result(started_at)

                connection_id = str(active_connector["id"])

                # Le schéma vient UNIQUEMENT de schema_store (base
                # interne InsightHub) — jamais de connexion à la base
                # cible réelle à ce stade.
                schema = await self._schema_cache.get_or_load(db_session, connection_id)

                if schema is None:
                    return self._no_schema_result(started_at)

                sql = await self._query_generator.generate_sql(
                    query.cleaned_text, schema
                )
                validation = self._query_validator.validate(sql)

                if not validation.is_valid:
                    return await self._handle_rejected(
                        db_session, query, schema, sql, validation.reason, started_at, connection_id
                    )

                # Toujours en mode preview : SQL généré + notice
                # explicite, jamais d'exécution réelle à ce stade du
                # projet (pas de données insérées, pas de connexion
                # persistante conservée après le scan du dump).
                return await self._preview_result(
                    db_session, query, schema, sql, started_at, connection_id
                )

        except Exception as exc:
            logger.error(f"[NL2SQLAgent] Erreur inattendue : {exc}")
            latency_ms = (time.perf_counter() - started_at) * 1000
            return AgentResult(
                source_type=self.source_type,
                chunks=[],
                latency_ms=latency_ms,
                error=str(exc),
            )

    # ------------------------------------------------------------
    # Résultats spécifiques
    # ------------------------------------------------------------

    def _no_active_database_result(self, started_at) -> AgentResult:
        latency_ms = (time.perf_counter() - started_at) * 1000
        chunk = RetrievedChunk(
            source_type=self.source_type,
            document_id="sql-no-active-db",
            chunk_id="sql-no-active-db",
            content=(
                "Aucune base de données n'est actuellement active. "
                "Activez une base dans la section 'Bases de données' "
                "pour poser des questions dessus."
            ),
            metadata={"status": "no_active_connection"},
            sql_score=1.0,
        )
        return AgentResult(source_type=self.source_type, chunks=[chunk], latency_ms=latency_ms)

    def _no_schema_result(self, started_at) -> AgentResult:
        latency_ms = (time.perf_counter() - started_at) * 1000
        chunk = RetrievedChunk(
            source_type=self.source_type,
            document_id="sql-no-schema",
            chunk_id="sql-no-schema",
            content="Le schéma de cette base n'a pas encore été scanné.",
            metadata={"status": "no_schema"},
            sql_score=1.0,
        )
        return AgentResult(source_type=self.source_type, chunks=[chunk], latency_ms=latency_ms)

    async def _preview_result(
        self, db_session, query, schema, sql, started_at, connection_id
    ) -> AgentResult:
        answer = (
            f"Voici la requête SQL générée pour votre question :\n\n"
            f"```sql\n{sql}\n```\n\n"
            f"{_PREVIEW_NOTICE}"
        )

        await self._query_logger.log(
            db_session,
            QueryExecutionLog(
                connection_id=connection_id,
                natural_language_question=query.cleaned_text,
                generated_sql=sql,
                engine_dialect=schema.engine_dialect,
                status="preview",
                error_message=None,
            ),
        )

        latency_ms = (time.perf_counter() - started_at) * 1000
        chunk = RetrievedChunk(
            source_type=self.source_type,
            document_id=f"sql-{connection_id}",
            chunk_id=f"sql-{connection_id}-preview-{int(time.time() * 1000)}",
            content=answer,
            metadata={"sql_query": sql, "status": "preview", "engine": schema.engine_dialect},
            sql_score=1.0,
        )
        return AgentResult(source_type=self.source_type, chunks=[chunk], latency_ms=latency_ms)

    async def _handle_rejected(
        self, db_session, query, schema, sql, reason, started_at, connection_id
    ) -> AgentResult:
        logger.warning(f"[NL2SQLAgent] Requête rejetée par le validator : {reason}")

        await self._query_logger.log(
            db_session,
            QueryExecutionLog(
                connection_id=connection_id,
                natural_language_question=query.cleaned_text,
                generated_sql=sql,
                engine_dialect=schema.engine_dialect,
                status="rejected",
                error_message=reason,
            ),
        )

        latency_ms = (time.perf_counter() - started_at) * 1000
        chunk = RetrievedChunk(
            source_type=self.source_type,
            document_id=f"sql-{connection_id}",
            chunk_id=f"sql-{connection_id}-rejected",
            content="Je ne peux pas exécuter cette requête pour des raisons de sécurité.",
            metadata={"sql_query": sql, "status": "rejected", "reason": reason},
            sql_score=1.0,
        )
        return AgentResult(
            source_type=self.source_type,
            chunks=[chunk],
            latency_ms=latency_ms,
        )