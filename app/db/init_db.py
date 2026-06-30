from sqlalchemy import text

from app.db.database import AsyncSessionLocal


async def initialize_database_schema() -> None:
    if AsyncSessionLocal is None:
        return

    async with AsyncSessionLocal() as session:
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS jira"))
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS servicenow"))
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS sharepoint"))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS jira.documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                external_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS jira.embeddings (
                chunk_id TEXT PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES jira.documents(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                embedding vector(384) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS servicenow.documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                external_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS servicenow.embeddings (
                chunk_id TEXT PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES servicenow.documents(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                embedding vector(384) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS sharepoint.documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                external_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS sharepoint.embeddings (
                chunk_id TEXT PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES sharepoint.documents(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                embedding vector(384) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.commit()
