import json
import logging
import time
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from app.admin.connectors.client_factory import build_client
from app.admin.connectors.crypto import (
    encrypt_auth_fields,
    decrypt_auth_fields,
    mask_auth_fields,
    MASK_PLACEHOLDER,
)
from app.admin.connectors.sync_factory import build_connectors_for_sync, build_transformer, SyncNotSupportedError

logger = logging.getLogger(__name__)
from app.admin.connectors.models import (
    ConnectorCreate,
    ConnectorDetail,
    ConnectorStatus,
    ConnectorSummary,
    ConnectorUpdate,
    DumpTableSummary,
    DumpUploadResponse,
    SourceType,
    SyncStats,
)
from app.admin.connectors.repository import ConnectorRepository

_UPDATABLE_FIELDS = {"instance_label", "sync_scope", "sync_frequency_minutes"}

_SQL_SOURCE_TYPES = {
    SourceType.POSTGRESQL,
    SourceType.MYSQL,
    SourceType.ORACLE,
    SourceType.MSSQL,
    SourceType.SQLITE,
}


class ConnectorService:

    def __init__(self, repository: Optional[ConnectorRepository] = None):
        self._repo = repository or ConnectorRepository()

    # ------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------

    async def list_connectors(self, session: AsyncSession) -> list[ConnectorSummary]:
        rows = await self._repo.list_all(session)
        return [self._to_summary(row) for row in rows]

    async def get_connector(
        self, session: AsyncSession, connector_id: UUID
    ) -> Optional[ConnectorDetail]:
        row = await self._repo.get_by_id(session, connector_id)
        return self._to_detail(row) if row else None

    # ------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------

    async def create_connector(
        self, session: AsyncSession, payload: ConnectorCreate
    ) -> ConnectorDetail:
        auth_encrypted = encrypt_auth_fields(payload.auth_fields)
        row = await self._repo.create(
            session,
            source_type=payload.source_type,
            instance_label=payload.instance_label,
            auth_encrypted=auth_encrypted,
            sync_scope=payload.sync_scope,
            sync_frequency_minutes=int(payload.sync_frequency_minutes),
        )
        self._sync_eventbridge_rule(row)
        return self._to_detail(row)

    async def update_connector(
        self, session: AsyncSession, connector_id: UUID, payload: ConnectorUpdate
    ) -> Optional[ConnectorDetail]:
        fields: dict[str, Any] = {}

        if payload.instance_label is not None:
            fields["instance_label"] = payload.instance_label
        if payload.sync_scope is not None:
            fields["sync_scope"] = json.dumps(payload.sync_scope)
        if payload.sync_frequency_minutes is not None:
            fields["sync_frequency_minutes"] = int(payload.sync_frequency_minutes)

        if payload.auth_fields is not None:
            existing_row = await self._repo.get_by_id(session, connector_id)
            existing_auth = (
                decrypt_auth_fields(existing_row["auth_encrypted"])
                if existing_row else {}
            )
            merged_auth = {**existing_auth}
            for key, value in payload.auth_fields.items():
                if value != MASK_PLACEHOLDER:
                    merged_auth[key] = value
            fields["auth_encrypted"] = encrypt_auth_fields(merged_auth)

        safe_fields = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_FIELDS or k == "auth_encrypted"
        }

        row = await self._repo.update(session, connector_id, safe_fields)
        if row is None:
            return None

        if "sync_frequency_minutes" in safe_fields:
            self._sync_eventbridge_rule(row)
        return self._to_detail(row)

    async def toggle_connector(
        self, session: AsyncSession, connector_id: UUID, enabled: bool
    ) -> Optional[ConnectorDetail]:
        row = await self._repo.get_by_id(session, connector_id)
        if row is None:
            return None

        if enabled and row["source_type"] in _SQL_SOURCE_TYPES:
            await self._repo.deactivate_all_sql_connectors(
                session, exclude_id=connector_id
            )

        row = await self._repo.update(session, connector_id, {"is_enabled": enabled})
        if row is None:
            return None
        self._sync_eventbridge_rule(row)
        return self._to_detail(row)

    async def delete_connector(self, session: AsyncSession, connector_id: UUID) -> bool:
        self._delete_eventbridge_rule(str(connector_id))
        return await self._repo.delete(session, connector_id)

    # ------------------------------------------------------------
    # EventBridge
    # ------------------------------------------------------------

    @staticmethod
    def _sync_eventbridge_rule(row: dict[str, Any]) -> None:
        if not settings.sync_lambda_arn:
            return
        try:
            from infrastructure.eventbridge import rules
            rules.create_or_update_rule(
                connector_id=str(row["id"]),
                frequency_minutes=row["sync_frequency_minutes"],
                lambda_arn=settings.sync_lambda_arn,
                enabled=row["is_enabled"],
            )
        except Exception as e:
            logger.error(
                f"[ConnectorService] Échec synchronisation règle EventBridge "
                f"pour connector_id={row['id']} : {e}"
            )

    @staticmethod
    def _delete_eventbridge_rule(connector_id: str) -> None:
        if not settings.sync_lambda_arn:
            return
        try:
            from infrastructure.eventbridge import rules
            rules.delete_rule(connector_id)
        except Exception as e:
            logger.error(
                f"[ConnectorService] Échec suppression règle EventBridge "
                f"pour connector_id={connector_id} : {e}"
            )

    # ------------------------------------------------------------
    # Actions (Phase 2)
    # ------------------------------------------------------------

    async def test_connection(self, session: AsyncSession, connector_id: UUID) -> bool:
        row = await self._repo.get_by_id(session, connector_id)
        if row is None:
            return False

        auth_fields = decrypt_auth_fields(row["auth_encrypted"])
        client = build_client(row["source_type"], auth_fields)
        return await client.test_connection()

    async def trigger_sync(self, session: AsyncSession, connector_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_by_id(session, connector_id)
        if row is None:
            raise ValueError("Connecteur introuvable")

        t0 = time.time()
        auth_fields = decrypt_auth_fields(row["auth_encrypted"])
        client = build_client(row["source_type"], auth_fields)
        sync_scope = row["sync_scope"] or {}

        aggregated = {"total_fetched": 0, "total_documents": 0, "total_chunks": 0}
        success = True
        error_message: Optional[str] = None

        try:
            connectors = build_connectors_for_sync(row["source_type"], client, sync_scope)
            transformer = build_transformer(row["source_type"])

            from app.ingestion.embeddings.embedder import Embedder
            from app.db.vector_store import VectorStore
            from app.ingestion.pipeline import IngestionPipeline

            embedder = Embedder()
            store = VectorStore()

            errors = []
            for connector in connectors:
                pipeline = IngestionPipeline(
                    connector, transformer, embedder, store,
                    connector_instance_id=str(connector_id),
                )
                result = await pipeline.run()
                aggregated["total_fetched"] += result.total_fetched
                aggregated["total_documents"] += result.total_documents
                aggregated["total_chunks"] += result.total_chunks
                if not result.success:
                    errors.append(result.error_message or "erreur inconnue")

            if errors:
                success = False
                error_message = "; ".join(errors)

        except SyncNotSupportedError as e:
            success = False
            error_message = str(e)
        except Exception as e:
            success = False
            error_message = f"Erreur inattendue pendant la synchronisation : {e}"

        duration_seconds = round(time.time() - t0, 1)
        stats = {
            "total_fetched": aggregated["total_fetched"],
            "total_documents": aggregated["total_documents"],
            "modified": aggregated["total_documents"],
            "duration_seconds": duration_seconds,
        }

        await self._repo.record_sync_result(
            session, connector_id, success=success, stats=stats, error=error_message,
        )

        return {"success": success, **stats, "error": error_message}

    async def get_decrypted_auth(
        self, session: AsyncSession, connector_id: UUID
    ) -> Optional[dict[str, str]]:
        row = await self._repo.get_by_id(session, connector_id)
        if row is None:
            return None
        return decrypt_auth_fields(row["auth_encrypted"])

    # ------------------------------------------------------------
    # Traduction ligne DB brute -> schéma API
    # ------------------------------------------------------------

    @staticmethod
    def _compute_status(row: dict[str, Any]) -> str:
        if not row["is_enabled"]:
            return ConnectorStatus.PAUSED
        if row["last_sync_status"] == "error":
            return ConnectorStatus.ERROR
        if row["last_sync_status"] == "success":
            return ConnectorStatus.ACTIVE
        return ConnectorStatus.PENDING

    def _to_summary(self, row: dict[str, Any]) -> ConnectorSummary:
        return ConnectorSummary(
            id=row["id"],
            source_type=row["source_type"],
            instance_label=row["instance_label"],
            status=self._compute_status(row),
            last_sync_at=row["last_sync_at"],
            sync_frequency_minutes=row["sync_frequency_minutes"],
        )

    def _to_detail(self, row: dict[str, Any]) -> ConnectorDetail:
        auth_fields = decrypt_auth_fields(row["auth_encrypted"])
        stats = SyncStats(**row["last_sync_stats"]) if row.get("last_sync_stats") else None

        return ConnectorDetail(
            id=row["id"],
            source_type=row["source_type"],
            instance_label=row["instance_label"],
            status=self._compute_status(row),
            last_sync_at=row["last_sync_at"],
            last_sync_status=row["last_sync_status"],
            last_sync_stats=stats,
            last_error=row["last_error"],
            sync_scope=row["sync_scope"] or {},
            sync_frequency_minutes=row["sync_frequency_minutes"],
            auth_fields=mask_auth_fields(auth_fields),
        )

    # ------------------------------------------------------------
    # Ingestion & Materialisation des Dumps SQL (Multi-moteur Sandbox)
    # ------------------------------------------------------------
    #
    # CORRECTIF FINAL : plus aucune tentative de garder une connexion
    # persistante vers la base cible. On scanne le schéma une fois
    # (via sandbox temporaire ou fichier SQLite direct), on le stocke
    # dans schema_store (base interne InsightHub), et c'est TOUT.
    # NL2SQLAgent n'exécute plus jamais de SQL réel — il répond
    # toujours à partir du schéma stocké (voir orchestrator.py).
    # ------------------------------------------------------------

    async def process_dump_upload(
        self,
        session: AsyncSession,
        file_name: str,
        file_bytes: bytes,
        engine_type: str = "sqlite",
        tenant_id: str | None = None,  # ignoré, conservé pour compat endpoint existant
    ) -> DumpUploadResponse:
        import uuid
        import sqlite3
        from pathlib import Path
        from sqlalchemy import create_engine
        from app.admin.connectors.sandbox_manager import SandboxManager
        from app.nl2sql.schema_scanner import SchemaScanner
        from app.nl2sql.factory import build_nl2sql_agent

        from app.admin.connectors.dump_parser import DumpParseError, DumpParser

        sandbox_mgr = SandboxManager()
        scanner = SchemaScanner()

        is_sqlite_binary = file_bytes.startswith(b"SQLite format 3\x00")
        is_postgres_binary = file_bytes.startswith(b"PGDMP")

        if is_postgres_binary:
            raise DumpParseError(
                "Le fichier fourni est un dump binaire PostgreSQL (PGDMP). Veuillez exporter votre base au format SQL texte (Plain text) avant de l'importer."
            )

        # Création du connecteur AVANT le scan — son UUID devient le
        # connection_id unique utilisé pour stocker/retrouver le schéma.
        connector_row = await self._repo.create(
            session,
            source_type=engine_type,
            instance_label=file_name,
            auth_encrypted=encrypt_auth_fields({}),
            sync_scope={},
            sync_frequency_minutes=0,
        )
        connection_id = str(connector_row["id"])

        # Cette base devient la base active — exclusivité SQL.
        await self._repo.deactivate_all_sql_connectors(
            session, exclude_id=connector_row["id"]
        )
        await self._repo.update(session, connector_row["id"], {"is_enabled": True})

        if is_sqlite_binary:
            # Fichier SQLite temporaire, uniquement pour le scan — pas
            # gardé comme connexion active pour l'exécution.
            sqlite_dir = Path(__file__).resolve().parent.parent.parent.parent / "sqlite_databases"
            sqlite_dir.mkdir(parents=True, exist_ok=True)
            safe_filename = f"sqlite_{uuid.uuid4().hex[:8]}.sqlite"
            filepath = sqlite_dir / safe_filename
            filepath.write_bytes(file_bytes)

            creator = lambda: sqlite3.connect(f"file:{filepath.resolve().as_posix()}?mode=ro", uri=True)
            temp_engine = create_engine("sqlite://", creator=creator)
            schema_scan = scanner.scan(temp_engine, connection_id=connection_id)
            temp_engine.dispose()

            agent = build_nl2sql_agent()
            await agent._schema_cache.invalidate(connection_id)
            await agent._schema_cache.refresh(session, schema_scan)

            return DumpUploadResponse(
                status="ok",
                connection_id=connection_id,
                engine_dialect="sqlite",
                database_name=file_name,
                tables=[
                    DumpTableSummary(
                        id=f"{t.name}-{uuid.uuid4().hex[:6]}",
                        name=t.name,
                        columns=[c.name for c in t.columns],
                        accessible=True,
                    )
                    for t in schema_scan.tables
                ]
            )

        # Dump texte (Postgres/MySQL/Oracle/SQL Server) : sandbox
        # temporaire, détruit à la fin du `with` — seul le schéma
        # scanné survit, dans schema_store.
        sql_text = file_bytes.decode("utf-8", errors="ignore")

        parser_instance = DumpParser()
        detected_engine = parser_instance.detect_engine(sql_text)
        if detected_engine:
            logger.info(f"[process_dump_upload] Auto-detected engine: {detected_engine} (requested: {engine_type})")
            engine_type = detected_engine

        with sandbox_mgr.create_sandbox(engine_type, sql_text, tenant_id=connection_id) as sandbox_engine:
            schema_scan = scanner.scan(sandbox_engine, connection_id=connection_id)

            agent = build_nl2sql_agent()
            await agent._schema_cache.invalidate(connection_id)
            await agent._schema_cache.refresh(session, schema_scan)

        return DumpUploadResponse(
            status="ok",
            connection_id=connection_id,
            engine_dialect=engine_type.lower(),
            database_name=file_name,
            tables=[
                DumpTableSummary(
                    id=f"{t.name}-{uuid.uuid4().hex[:6]}",
                    name=t.name,
                    columns=[c.name for c in t.columns],
                    accessible=True,
                )
                for t in schema_scan.tables
            ]
        )