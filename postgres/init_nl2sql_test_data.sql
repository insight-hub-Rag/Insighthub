-- ============================================================
-- InsightHub — NL2SQL : création de la base de test séparée
-- NOTE: Ce fichier est exécuté dans le contexte de la base
-- "insighthub" (POSTGRES_DB). Il crée la base nl2sql_test
-- via une fonction helper puis y insère les données via
-- dblink. Les tables et données sont créées par le script
-- shell init_nl2sql_test_data.sh.
-- ============================================================

-- Crée la base si elle n'existe pas déjà (idempotent)
SELECT 'CREATE DATABASE insighthub_nl2sql_test OWNER insighthub'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'insighthub_nl2sql_test'
)\gexec