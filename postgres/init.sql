-- ============================================================
-- InsightHub — Initialisation base de données
-- Schémas séparés par source d'ingestion (Strategy Pattern côté SQL)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- SCHÉMA PUBLIC — tables transverses, communes à toutes les sources
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.ingestion_sources (
    source_type  TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.sync_history (
    id             BIGSERIAL PRIMARY KEY,
    source_type    TEXT NOT NULL REFERENCES public.ingestion_sources(source_type),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    success        BOOLEAN,
    total_fetched  INTEGER NOT NULL DEFAULT 0,
    total_inserted INTEGER NOT NULL DEFAULT 0,
    total_skipped  INTEGER NOT NULL DEFAULT 0,
    last_cursor    TEXT,
    error_message  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_history_source
    ON public.sync_history (source_type, started_at DESC);

INSERT INTO public.ingestion_sources (source_type, display_name, enabled) VALUES
    ('jira', 'Jira', TRUE)
ON CONFLICT (source_type) DO NOTHING;

-- ------------------------------------------------------------
-- SCHÉMA JIRA
-- ------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS jira;

CREATE TABLE IF NOT EXISTS jira.documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_id)
);

CREATE TABLE IF NOT EXISTS jira.embeddings (
    chunk_id    TEXT PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES jira.documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(1024) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jira_documents_external_id
    ON jira.documents (external_id);

CREATE INDEX IF NOT EXISTS idx_jira_embeddings_document_id
    ON jira.embeddings (document_id);

CREATE INDEX IF NOT EXISTS idx_jira_embeddings_vector
    ON jira.embeddings USING hnsw (embedding vector_cosine_ops);