from sqlalchemy import text

from app.db.database import AsyncSessionLocal


async def initialize_database_schema() -> None:
    if AsyncSessionLocal is None:
        return

    async with AsyncSessionLocal() as session:
        # Une base CI fraîche n'exécute pas les scripts
        # docker-entrypoint-initdb.d du docker-compose local. Les types
        # vectoriels doivent donc être disponibles avant la création des
        # tables *.embeddings.
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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

        # connector_configs 
        
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS connector_configs (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                source_type             TEXT NOT NULL,
                instance_label          TEXT NOT NULL,
                is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
                auth_encrypted          TEXT NOT NULL,
                sync_scope              JSONB NOT NULL DEFAULT '{}'::jsonb,
                sync_frequency_minutes  INTEGER NOT NULL DEFAULT 15,
                last_sync_at            TIMESTAMPTZ,
                last_sync_status        TEXT,
                last_sync_stats         JSONB,
                last_error              TEXT,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (source_type, instance_label)
            )
        """))

        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_connector_configs_source_type "
            "ON connector_configs (source_type)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_connector_configs_enabled "
            "ON connector_configs (is_enabled) WHERE is_enabled = TRUE"
        ))

        # chat_conversations / chat_messages — historique du chat (sidebar
        # "Aujourd'hui"). Structure déduite exactement des requêtes SQL de
        # app/db/chat_history.py (ce module existait déjà, sans jamais
        # avoir été inclus dans un script d'auto-init nulle part — d'où
        # la table qui disparaissait à chaque reset de volume, sans
        # aucun moyen de la recréer automatiquement jusqu'à maintenant).
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL DEFAULT '',
                source       TEXT NOT NULL DEFAULT '',
                latency_ms   DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                group_label  TEXT NOT NULL DEFAULT '',
                favorite     BOOLEAN NOT NULL DEFAULT FALSE,
                trashed      BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))

        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id               TEXT PRIMARY KEY,
                conversation_id  TEXT NOT NULL,
                role             TEXT NOT NULL,
                content          TEXT NOT NULL DEFAULT '',
                sources          JSONB NOT NULL DEFAULT '[]'::jsonb,
                latency_ms       DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id "
            "ON chat_messages (conversation_id)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chat_conversations_trashed "
            "ON chat_conversations (trashed, created_at DESC)"
        ))

        await session.commit()
