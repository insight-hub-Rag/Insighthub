"""
app/nl2sql/orchestrator.py

NL2SQLAgent — point d'entrée du module, appelable par l'AgentManager
exactement comme JiraAgent/ConfluenceAgent/SharePointAgent, MAIS sans
hériter de BaseAgent (le pipeline est totalement différent : pas de
vector/BM25/RRF). Respecte uniquement le contrat duck-typed défini par
le Protocol BaseAgent dans app/rag/interfaces.py :
  - attribut source_type: str
  - async def run(query, routing) -> AgentResult

Pipeline complet exécuté à chaque question :
  schema_cache.get_or_load()
    → query_generator.generate_sql()
    → query_validator.validate()
    → query_executor.execute()  [si valide]
    → query_optimizer.suggest()  [si lent/tronqué/rejeté]
    → response_formatter.format()
    → query_logger.log()

Toutes les opérations synchrones (connection.py, query_executor.py)
sont déportées via asyncio.to_thread() pour ne jamais bloquer l'event
loop FastAPI partagé avec le reste du pipeline RAG.
"""

import asyncio
import logging
import time

from app.core.models import AgentResult, PreprocessedQuery, RetrievedChunk, RoutingDecision
from app.db.database import AsyncSessionLocal
from app.nl2sql.connection import target_connection_manager
from app.nl2sql.models import NL2SQLConfig, QueryExecutionLog, SchemaScanResult
from app.nl2sql.query_executor import QueryExecutor
from app.nl2sql.query_generator import QueryGenerator
from app.nl2sql.query_logger import QueryLogger
from app.nl2sql.query_optimizer import QueryOptimizer
from app.nl2sql.query_validator import QueryValidator
from app.nl2sql.response_formatter import ResponseFormatter
from app.nl2sql.schema_cache import SchemaCache
from app.nl2sql.schema_scanner import SchemaScanner
from app.nl2sql.schema_store import SchemaStore

logger = logging.getLogger(__name__)


class NL2SQLAgent:

    source_type = "sql"   # requis par le contrat duck-typed de interfaces.py

    def __init__(
        self,
        config: NL2SQLConfig,
        schema_cache: SchemaCache,
        query_generator: QueryGenerator,
        query_optimizer: QueryOptimizer,
        response_formatter: ResponseFormatter,
    ):
        self._config = config
        self._schema_cache = schema_cache
        self._schema_scanner = SchemaScanner()
        self._schema_store = SchemaStore()
        self._query_generator = query_generator
        self._query_validator = QueryValidator()
        self._query_executor = QueryExecutor()
        self._query_optimizer = query_optimizer
        self._response_formatter = response_formatter
        self._query_logger = QueryLogger()

    async def run(
        self,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> AgentResult:
        started_at = time.perf_counter()

        try:
            async with AsyncSessionLocal() as db_session:
                schema = await self._schema_cache.get_or_load(
                    db_session, self._config.connection_id
                )

                if schema is None:
                    schema = await self._perform_scan(db_session)

                sql = await self._query_generator.generate_sql(
                    query.cleaned_text, schema
                )
                validation = self._query_validator.validate(sql)

                if not validation.is_valid:
                    return await self._handle_rejected(
                        db_session, query, schema, sql, validation.reason, started_at
                    )

                outcome = await asyncio.to_thread(
                    self._execute_sql, sql, schema.engine_dialect
                )

                status = self._determine_status(outcome)
                suggestion = None
                if status in ("optimized", "rejected"):
                    suggestion = await self._query_optimizer.suggest(
                        sql=sql,
                        exec_time_ms=outcome.exec_time_ms,
                        truncated=outcome.truncated,
                        error_message=outcome.error_message,
                    )

                answer = await self._response_formatter.format(
                    query.cleaned_text, outcome
                )

                await self._query_logger.log(
                    db_session,
                    QueryExecutionLog(
                        connection_id=self._config.connection_id,
                        natural_language_question=query.cleaned_text,
                        generated_sql=sql,
                        engine_dialect=schema.engine_dialect,
                        status=status,
                        exec_time_ms=outcome.exec_time_ms,
                        suggested_improvement=suggestion,
                        error_message=outcome.error_message,
                    ),
                )

                latency_ms = (time.perf_counter() - started_at) * 1000
                return self._build_agent_result(
                    sql=sql,
                    answer=answer,
                    schema=schema,
                    status=status,
                    exec_time_ms=outcome.exec_time_ms,
                    suggestion=suggestion,
                    latency_ms=latency_ms,
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
    # API publique — utilisée par l'endpoint admin (app/api/router.py)
    # ------------------------------------------------------------

    async def rescan_schema(self) -> SchemaScanResult:
        """
        Force un re-scan du schéma de la base cible et le persiste
        (store + cache), indépendamment de toute question utilisateur.
        Ouvre sa propre session DB, dédiée à cet appel — c'est le point
        d'entrée public à utiliser depuis un endpoint FastAPI, plutôt
        que d'accéder aux méthodes internes de l'agent.
        """
        async with AsyncSessionLocal() as db_session:
            return await self._perform_scan(db_session)

    # ------------------------------------------------------------
    # Étapes internes
    # ------------------------------------------------------------

    async def _perform_scan(self, db_session) -> SchemaScanResult:
        engine = await asyncio.to_thread(
            target_connection_manager.get_engine, self._config
        )
        schema = await asyncio.to_thread(
            self._schema_scanner.scan, engine, self._config.connection_id
        )
        await self._schema_cache.refresh(db_session, schema)
        return schema

    def _execute_sql(self, sql: str, dialect: str):
        with target_connection_manager.get_session(self._config) as session:
            return self._query_executor.execute(session, sql, dialect)

    def _determine_status(self, outcome) -> str:
        if not outcome.success:
            return "rejected"
        if outcome.exec_time_ms >= self._config.latency_threshold_ms or outcome.truncated:
            return "optimized"
        return "accepted"

    async def _handle_rejected(
        self, db_session, query, schema, sql, reason, started_at
    ) -> AgentResult:
        """Cas où query_validator bloque la requête AVANT toute
        exécution — aucun accès à la base cible n'a lieu, cohérent
        avec la garantie READ-ONLY béton demandée."""
        logger.warning(f"[NL2SQLAgent] Requête rejetée par le validator : {reason}")

        await self._query_logger.log(
            db_session,
            QueryExecutionLog(
                connection_id=self._config.connection_id,
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
            document_id=f"sql-{self._config.connection_id}",
            chunk_id=f"sql-{self._config.connection_id}-rejected",
            content="Je ne peux pas exécuter cette requête pour des raisons de sécurité.",
            metadata={"sql_query": sql, "status": "rejected", "reason": reason},
            sql_score=1.0,
        )
        return AgentResult(
            source_type=self.source_type,
            chunks=[chunk],
            latency_ms=latency_ms,
        )

    def _build_agent_result(
        self, sql, answer, schema, status, exec_time_ms, suggestion, latency_ms
    ) -> AgentResult:
        chunk = RetrievedChunk(
            source_type=self.source_type,
            document_id=f"sql-{self._config.connection_id}",
            chunk_id=f"sql-{self._config.connection_id}-{int(time.time() * 1000)}",
            content=answer,
            metadata={
                "sql_query": sql,
                "engine": schema.engine_dialect,
                "status": status,
                "exec_time_ms": exec_time_ms,
                "suggested_improvement": suggestion,
            },
            sql_score=1.0,
        )
        return AgentResult(
            source_type=self.source_type,
            chunks=[chunk],
            latency_ms=latency_ms,
        )