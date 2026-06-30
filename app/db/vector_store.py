"""
VectorStore : couche d'accès aux données pour les documents et leurs
chunks vectorisés. Route automatiquement vers le bon schéma SQL selon
`source_type` ('jira' -> schéma `jira`, etc.).

Classe injectable (plutôt que des fonctions de module avec un singleton
global) : testable avec une session mockée, cycle de vie explicite.
"""

import json
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk
from app.db.database import AsyncSessionLocal

# Schémas autorisés par source. Ajouter une source = ajouter une ligne ici
# (et créer le schéma correspondant dans postgres/init.sql).
SCHEMA_BY_SOURCE = {
    "jira": "jira",
    "servicenow": "servicenow",
    "sharepoint": "sharepoint",
}


class VectorStore:

    def __init__(self, session_factory=AsyncSessionLocal):
        self._session_factory = session_factory

    async def upsert_document_with_chunks(
        self, source_type: str, document_id: str, chunks: list[Chunk]
    ) -> int:
        """
        Crée ou met à jour le document parent, puis upsert tous ses chunks.
        Opération unique et cohérente : pas besoin pour l'appelant de gérer
        document_id séparément des chunks (ils le portent déjà).

        Returns:
            Nombre de chunks insérés/mis à jour.
        """
        if self._session_factory is None:
            logger.warning(
                f"[VectorStore] Pas de base configurée — chunks ignorés "
                f"(source={source_type}, document={document_id})"
            )
            return 0

        schema = self._schema_for(source_type)
        title = self._extract_title(chunks)

        async with self._session_factory() as session:
            await self._upsert_document(session, schema, document_id, title, chunks)
            count = await self._upsert_chunks(session, schema, document_id, chunks)
            await session.commit()
            return count

    async def _upsert_document(
        self, session: AsyncSession, schema: str, document_id: str, title: str, chunks: list[Chunk]
    ) -> None:
        metadata = chunks[0].metadata if chunks else {}
        await session.execute(
            text(f"""
                INSERT INTO {schema}.documents (external_id, title, metadata)
                VALUES (:external_id, :title, :metadata)
                ON CONFLICT (external_id) DO UPDATE SET
                    title      = EXCLUDED.title,
                    metadata   = EXCLUDED.metadata,
                    updated_at = now()
            """),
            {
                "external_id": document_id,
                "title": title,
                "metadata": json.dumps(metadata),
            },
        )

    async def _upsert_chunks(
        self, session: AsyncSession, schema: str, document_id: str, chunks: list[Chunk]
    ) -> int:
        count = 0
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning(f"[VectorStore] Chunk sans embedding ignoré : {chunk.chunk_id}")
                continue

            await session.execute(
                text(f"""
                    INSERT INTO {schema}.embeddings (chunk_id, document_id, content, embedding, metadata)
                    VALUES (
                        :chunk_id,
                        (SELECT id FROM {schema}.documents WHERE external_id = :document_id),
                        :content, :embedding, :metadata
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        content   = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        metadata  = EXCLUDED.metadata
                """),
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": document_id,
                    "content": chunk.content,
                    "embedding": str(chunk.embedding),
                    "metadata": json.dumps(chunk.metadata),
                },
            )
            count += 1
        return count

    @staticmethod
    def _schema_for(source_type: str) -> str:
        schema = SCHEMA_BY_SOURCE.get(source_type)
        if schema is None:
            raise ValueError(
                f"Source inconnue : '{source_type}'. "
                f"Sources supportées : {list(SCHEMA_BY_SOURCE)}"
            )
        return schema

    @staticmethod
    def _extract_title(chunks: list[Chunk]) -> str:
        """Le titre du document est dérivé du premier chunk de type 'body'."""
        for chunk in chunks:
            if chunk.metadata.get("chunk_type") == "body":
                first_line = chunk.content.split("\n", 1)[0]
                return first_line
        return chunks[0].content[:200] if chunks else ""