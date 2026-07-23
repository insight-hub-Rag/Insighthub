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
                embedding vector(1024) NOT NULL,
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
                embedding vector(1024) NOT NULL,
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
                embedding vector(1024) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        # ── NL2SQL monitoring tables (public schema, insighthub DB) ────────────
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS nl2sql_schema_snapshots (
                id              BIGSERIAL PRIMARY KEY,
                connection_id   TEXT NOT NULL,
                engine_dialect  TEXT NOT NULL,
                schema_json     JSONB NOT NULL,
                scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_active       BOOLEAN NOT NULL DEFAULT TRUE
            )
        """))

        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nl2sql_snapshots_active
                ON nl2sql_schema_snapshots (connection_id, is_active)
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS nl2sql_query_execution_logs (
                id                        BIGSERIAL PRIMARY KEY,
                connection_id             TEXT NOT NULL,
                natural_language_question TEXT NOT NULL,
                generated_sql             TEXT NOT NULL,
                engine_dialect            TEXT NOT NULL,
                source_label              TEXT NOT NULL DEFAULT 'SQL Database',
                status                    TEXT NOT NULL,
                exec_time_ms              DOUBLE PRECISION,
                suggested_improvement     TEXT,
                error_message             TEXT,
                created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nl2sql_logs_created_at
                ON nl2sql_query_execution_logs (created_at DESC)
        """))

        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nl2sql_logs_status
                ON nl2sql_query_execution_logs (status)
        """))

        # ── Chat conversations history ─────────────────────────────────────────
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                source       TEXT NOT NULL DEFAULT '',
                latency_ms   INTEGER NOT NULL DEFAULT 0,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                group_label  TEXT NOT NULL DEFAULT 'Aujourd''hui',
                favorite     BOOLEAN NOT NULL DEFAULT FALSE,
                trashed      BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))

        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_conversations_created_at
                ON chat_conversations (created_at DESC)
        """))

        # ── Chat messages (échanges Q/R par conversation) ──────────────────────
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
                latency_ms      INTEGER NOT NULL DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_conv_id
                ON chat_messages (conversation_id, created_at ASC)
        """))

        await session.commit()
