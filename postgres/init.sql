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
    ('jira', 'Jira', TRUE),
    ('servicenow', 'ServiceNow', FALSE),
    ('sharepoint', 'SharePoint', FALSE),
    ('confluence', 'Confluence', TRUE)
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



-- ------------------------------------------------------------
-- SCHÉMA CONFLUENCE
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS confluence;

CREATE TABLE IF NOT EXISTS confluence.documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_id)
);

CREATE TABLE IF NOT EXISTS confluence.embeddings (
    chunk_id    TEXT PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES confluence.documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(1024) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_confluence_documents_external_id
    ON confluence.documents (external_id);

CREATE INDEX IF NOT EXISTS idx_confluence_embeddings_document_id
    ON confluence.embeddings (document_id);

CREATE INDEX IF NOT EXISTS idx_confluence_embeddings_vector
    ON confluence.embeddings USING hnsw (embedding vector_cosine_ops);

-- ------------------------------------------------------------
-- FULL-TEXT SEARCH (BM25 approximatif) — JIRA
-- ------------------------------------------------------------
-- Colonne générée automatiquement à partir du contenu, jamais modifiée
-- à la main. Config 'french' pour gérer les accents/pluriels/stopwords
-- français correctement dans le classement par pertinence.
ALTER TABLE jira.embeddings
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('french', content)) STORED;

CREATE INDEX IF NOT EXISTS idx_jira_embeddings_tsv
    ON jira.embeddings USING gin (content_tsv);

-- ------------------------------------------------------------
-- FULL-TEXT SEARCH (BM25 approximatif) — CONFLUENCE
-- ------------------------------------------------------------
ALTER TABLE confluence.embeddings
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('french', content)) STORED;

CREATE INDEX IF NOT EXISTS idx_confluence_embeddings_tsv
    ON confluence.embeddings USING gin (content_tsv);
-- ------------------------------------------------------------
-- SCHÉMA SERVICENOW
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS servicenow;

CREATE TABLE IF NOT EXISTS servicenow.documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_id)
);

CREATE TABLE IF NOT EXISTS servicenow.embeddings (
    chunk_id    TEXT PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES servicenow.documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(1024) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_servicenow_documents_external_id
    ON servicenow.documents (external_id);

CREATE INDEX IF NOT EXISTS idx_servicenow_embeddings_document_id
    ON servicenow.embeddings (document_id);

CREATE INDEX IF NOT EXISTS idx_servicenow_embeddings_vector
    ON servicenow.embeddings USING hnsw (embedding vector_cosine_ops);

ALTER TABLE servicenow.embeddings
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('french', content)) STORED;

CREATE INDEX IF NOT EXISTS idx_servicenow_embeddings_tsv
    ON servicenow.embeddings USING gin (content_tsv);