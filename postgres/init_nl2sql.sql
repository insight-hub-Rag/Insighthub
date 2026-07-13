-- ============================================================
-- InsightHub — NL2SQL : tables de monitoring/cache
-- Tourne sur la base `insighthub` (POSTGRES_DB), pas de \c ici.
-- ============================================================

CREATE TABLE IF NOT EXISTS nl2sql_schema_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    connection_id   TEXT NOT NULL,
    engine_dialect  TEXT NOT NULL,
    schema_json     JSONB NOT NULL,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_nl2sql_snapshots_active
    ON nl2sql_schema_snapshots (connection_id, is_active);

CREATE TABLE IF NOT EXISTS nl2sql_query_execution_logs (
    id                          BIGSERIAL PRIMARY KEY,
    connection_id               TEXT NOT NULL,
    natural_language_question   TEXT NOT NULL,
    generated_sql                TEXT NOT NULL,
    engine_dialect               TEXT NOT NULL,
    source_label                 TEXT NOT NULL DEFAULT 'SQL Database',
    status                       TEXT NOT NULL,
    exec_time_ms                 DOUBLE PRECISION,
    suggested_improvement        TEXT,
    error_message                TEXT,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nl2sql_logs_created_at
    ON nl2sql_query_execution_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_nl2sql_logs_status
    ON nl2sql_query_execution_logs (status);