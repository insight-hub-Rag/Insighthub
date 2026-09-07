-- ============================================================
-- InsightHub — Reports / HR Analytics
-- Schéma séparé pour le dashboard "Rapport de productivité RH"
-- Score de satisfaction/complexité pré-calculé par LLM (Bedrock),
-- jamais recalculé à la demande (voir reports.ticket_scores).
-- ============================================================

CREATE SCHEMA IF NOT EXISTS reports;

-- ------------------------------------------------------------
-- EMPLOYEES — rattachement provisoire par nom, en attendant
-- l'authentification (en cours par un autre membre de l'équipe).
-- Quand l'auth sera prête : ajout d'une colonne user_id nullable
-- en FK, remplie a posteriori — pas de migration destructive.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reports.employees (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT NOT NULL,
    team         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (display_name)
);

-- ------------------------------------------------------------
-- TICKET_SCORES — résultat du scoring LLM, calculé une seule
-- fois par ticket fermé (job séparé, pas dans le GET dashboard).
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reports.ticket_scores (
    ticket_id           TEXT NOT NULL,
    source_type         TEXT NOT NULL,      -- 'jira' | 'servicenow'
    employee_id         UUID REFERENCES reports.employees(id),
    is_closed           BOOLEAN NOT NULL,
    resolution_hours    NUMERIC,
    complexity_score    NUMERIC,             -- 0-1, sorti par le LLM
    satisfaction_score  NUMERIC,             -- 0-1, sorti par le LLM
    llm_reasoning       TEXT,                 -- justification courte (soutenance)
    prompt_version      TEXT NOT NULL,        -- versioning du prompt
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticket_id, source_type)
);

CREATE INDEX IF NOT EXISTS idx_ticket_scores_employee
    ON reports.ticket_scores (employee_id);