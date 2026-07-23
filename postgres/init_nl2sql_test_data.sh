#!/bin/bash
# ============================================================
# InsightHub — NL2SQL : schéma + données fictives de test
# Exécuté par docker-entrypoint-initdb.d après la création
# de la base insighthub_nl2sql_test.
# ============================================================
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "insighthub_nl2sql_test" <<-EOSQL
    CREATE TABLE IF NOT EXISTS employees (
        id           SERIAL PRIMARY KEY,
        full_name    TEXT NOT NULL,
        department   TEXT NOT NULL,
        salary       NUMERIC(10, 2) NOT NULL,
        hired_at     DATE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS conges (
        id           SERIAL PRIMARY KEY,
        employee_id  INTEGER NOT NULL REFERENCES employees(id),
        start_date   DATE NOT NULL,
        end_date     DATE NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending'
    );

    CREATE TABLE IF NOT EXISTS projets (
        id           SERIAL PRIMARY KEY,
        name         TEXT NOT NULL,
        department   TEXT NOT NULL,
        started_at   DATE NOT NULL,
        status       TEXT NOT NULL DEFAULT 'active'
    );

    CREATE TABLE IF NOT EXISTS tickets (
        id           SERIAL PRIMARY KEY,
        project_id   INTEGER NOT NULL REFERENCES projets(id),
        title        TEXT NOT NULL,
        priority     TEXT NOT NULL DEFAULT 'medium',
        resolved     BOOLEAN NOT NULL DEFAULT FALSE
    );

    INSERT INTO employees (full_name, department, salary, hired_at) VALUES
        ('Douae doudy',   'IT',      18000, '2022-01-15'),
        ('Salma Bennani', 'RH',      15000, '2021-06-01'),
        ('Karim Idrissi', 'Finance', 22000, '2020-03-10')
    ON CONFLICT DO NOTHING;

    INSERT INTO projets (name, department, started_at, status) VALUES
        ('InsightHub', 'IT', '2026-01-01', 'active')
    ON CONFLICT DO NOTHING;

    INSERT INTO conges (employee_id, start_date, end_date, status) VALUES
        (1, '2026-08-01', '2026-08-10', 'approved'),
        (2, '2026-07-15', '2026-07-20', 'pending')
    ON CONFLICT DO NOTHING;

    INSERT INTO tickets (project_id, title, priority, resolved) VALUES
        (1, 'Bug login SSO',       'high',   FALSE),
        (1, 'Lenteur dashboard',   'medium', TRUE)
    ON CONFLICT DO NOTHING;
EOSQL
