-- ============================================================
-- InsightHub — Admin des connecteurs (écran "Connecteurs")
-- Une ligne = une instance connectée (ex: "Jira — Production").
-- Pas de colonne "status" séparée : le badge Actif/Échec affiché
-- côté UI est déduit de is_enabled + last_sync_status (voir
-- app/admin/connectors/models.py) — évite un état dupliqué qui
-- pourrait diverger de la réalité.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- requis pour gen_random_uuid()

CREATE TABLE IF NOT EXISTS connector_configs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_type             TEXT NOT NULL,              -- 'jira' | 'confluence' | 'sharepoint' | 'servicenow'
    instance_label          TEXT NOT NULL,              -- "Jira — Production"

    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,   -- le toggle actif/inactif de l'UI

    -- Authentification chiffrée (URL, email, token...) — sérialisée en
    -- JSON puis chiffrée avant stockage, jamais en clair. Le champ est
    -- volontairement TEXT (pas JSONB) : son contenu est un blob chiffré,
    -- pas une structure interrogeable par Postgres.
    auth_encrypted          TEXT NOT NULL,

    -- Périmètre de synchronisation (projets, types de tickets, statuts
    -- exclus...) — structure libre selon source_type, d'où JSONB.
    sync_scope              JSONB NOT NULL DEFAULT '{}'::jsonb,

    sync_frequency_minutes  INTEGER NOT NULL DEFAULT 15,

    last_sync_at            TIMESTAMPTZ,
    last_sync_status        TEXT,               -- 'success' | 'error' | NULL (jamais synchronisé)
    last_sync_stats         JSONB,              -- {"total_fetched":847,"modified":12,"duration_seconds":4.2}
    last_error              TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_type, instance_label)
);

CREATE INDEX IF NOT EXISTS idx_connector_configs_source_type
    ON connector_configs (source_type);

CREATE INDEX IF NOT EXISTS idx_connector_configs_enabled
    ON connector_configs (is_enabled)
    WHERE is_enabled = TRUE;