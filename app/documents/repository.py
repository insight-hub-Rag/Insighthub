"""
Documents Clients — Repository (accès base de données).

Table cible : public.client_documents
Créée dans init.sql au démarrage de l'app via initialize_database_schema().
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentStatus, DocumentOut

logger = logging.getLogger(__name__)


class DocumentRepository:

    # ------------------------------------------------------------------
    # DDL — appelé depuis init_db au démarrage
    # ------------------------------------------------------------------

    @staticmethod
    async def ensure_table(session: AsyncSession) -> None:
        """Crée la table client_documents si elle n'existe pas."""
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS public.client_documents (
                id          TEXT        PRIMARY KEY,
                filename    TEXT        NOT NULL,
                file_type   TEXT        NOT NULL,
                file_size   BIGINT      NOT NULL DEFAULT 0,
                status      TEXT        NOT NULL DEFAULT 'UPLOADING',
                chunk_count INTEGER     NOT NULL DEFAULT 0,
                tenant_id   TEXT        NOT NULL DEFAULT 'default',
                user_id     TEXT,
                s3_key      TEXT,
                error       TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await session.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        session: AsyncSession,
        filename: str,
        file_type: str,
        file_size: int,
        tenant_id: str = "default",
        user_id: Optional[str] = None,
        s3_key: Optional[str] = None,
    ) -> DocumentOut:
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await session.execute(
            text("""
                INSERT INTO public.client_documents
                    (id, filename, file_type, file_size, status, tenant_id, user_id, s3_key, created_at, updated_at)
                VALUES
                    (:id, :filename, :file_type, :file_size, :status, :tenant_id, :user_id, :s3_key, :created_at, :updated_at)
            """),
            {
                "id": doc_id,
                "filename": filename,
                "file_type": file_type,
                "file_size": file_size,
                "status": DocumentStatus.UPLOADED.value,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "s3_key": s3_key,
                "created_at": now,
                "updated_at": now,
            }
        )
        await session.commit()
        return await self.get_by_id(session, doc_id)

    async def list_all(
        self,
        session: AsyncSession,
        tenant_id: str = "default",
        user_id: Optional[str] = None,
    ) -> list[DocumentOut]:
        query = "SELECT * FROM public.client_documents WHERE tenant_id = :tenant_id"
        params: dict = {"tenant_id": tenant_id}
        if user_id:
            query += " AND user_id = :user_id"
            params["user_id"] = user_id
        query += " ORDER BY created_at DESC"
        result = await session.execute(text(query), params)
        rows = result.mappings().all()
        return [self._row_to_model(row) for row in rows]

    async def get_by_id(self, session: AsyncSession, doc_id: str) -> Optional[DocumentOut]:
        result = await session.execute(
            text("SELECT * FROM public.client_documents WHERE id = :id"),
            {"id": doc_id}
        )
        row = result.mappings().first()
        return self._row_to_model(row) if row else None

    async def update_status(
        self,
        session: AsyncSession,
        doc_id: str,
        status: DocumentStatus,
        chunk_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        await session.execute(
            text("""
                UPDATE public.client_documents
                SET status = :status,
                    chunk_count = :chunk_count,
                    error = :error,
                    updated_at = now()
                WHERE id = :id
            """),
            {"id": doc_id, "status": status.value, "chunk_count": chunk_count, "error": error}
        )
        await session.commit()

    async def delete(self, session: AsyncSession, doc_id: str) -> bool:
        result = await session.execute(
            text("DELETE FROM public.client_documents WHERE id = :id"),
            {"id": doc_id}
        )
        await session.commit()
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_model(row) -> DocumentOut:
        return DocumentOut(
            id=row["id"],
            filename=row["filename"],
            file_type=row["file_type"],
            file_size=row["file_size"],
            status=DocumentStatus(row["status"]),
            chunk_count=row["chunk_count"],
            tenant_id=row["tenant_id"],
            user_id=row.get("user_id"),
            s3_key=row.get("s3_key"),
            error=row.get("error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
