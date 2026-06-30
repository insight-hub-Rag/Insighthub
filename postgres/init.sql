-- ============================================================
-- InsightHub — Initialisation base de données
-- Schémas séparés par source d'ingestion (Strategy Pattern côté SQL)
-- ============================================================

-- Extension pgvector (une seule fois, au niveau du cluster)
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- SCHÉMA PUBLIC — tables transverses, communes à toutes les sources
-- ------------------------------------------------------------

-- Registre des sources connues (utile pour l'API, le monitoring,
-- et pour savoir quelles sources sont actives sans hardcoder une liste).
CREATE TABLE IF NOT EXISTS public.ingestion_sources (
    source_type   TEXT PRIMARY KEY,        -- 'jira', 'servicenow', 'sharepoint'...
    display_name  TEXT NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historique des syncs, toutes sources confondues (utile pour dashboards/monitoring).
CREATE TABLE IF NOT EXISTS public.sync_history (
    id              BIGSERIAL PRIMARY KEY,
    source_type     TEXT NOT NULL REFERENCES public.ingestion_sources(source_type),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    success         BOOLEAN,
    total_fetched   INTEGER NOT NULL DEFAULT 0,
    total_inserted  INTEGER NOT NULL DEFAULT 0,
    total_skipped   INTEGER NOT NULL DEFAULT 0,
    last_cursor     TEXT,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_history_source
    ON public.sync_history (source_type, started_at DESC);

-- Seed des sources connues dès aujourd'hui (Jira actif, le reste préparé mais désactivé).
INSERT INTO public.ingestion_sources (source_type, display_name, enabled) VALUES
    ('jira', 'Jira', TRUE),
    ('servicenow', 'ServiceNow', FALSE),
    ('sharepoint', 'SharePoint', FALSE)
ON CONFLICT (source_type) DO NOTHING;


-- ------------------------------------------------------------
-- SCHÉMA JIRA — tout ce qui est spécifique à la source Jira
-- ------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS jira;

-- Un document = une issue Jira (granularité métier).
CREATE TABLE IF NOT EXISTS jira.documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id   TEXT NOT NULL,           -- ex: 'PROJ-123'
    title         TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_id)
);

-- Un chunk = un fragment de texte vectorisé (corps de l'issue ou un commentaire).
CREATE TABLE IF NOT EXISTS jira.embeddings (
    chunk_id      TEXT PRIMARY KEY,         -- ex: 'jira-PROJ-123-0'
    document_id   UUID NOT NULL REFERENCES jira.documents(id) ON DELETE CASCADE,
    content       TEXT NOT NULL,
    embedding     vector(384) NOT NULL,      -- 384 = dimension du modèle sentence-transformers all-MiniLM-L6-v2 (cf. config.py)
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jira_documents_external_id
    ON jira.documents (external_id);

CREATE INDEX IF NOT EXISTS idx_jira_embeddings_document_id
    ON jira.embeddings (document_id);

-- Index vectoriel pour la recherche par similarité (HNSW : bon compromis vitesse/précision).
CREATE INDEX IF NOT EXISTS idx_jira_embeddings_vector
    ON jira.embeddings USING hnsw (embedding vector_cosine_ops);