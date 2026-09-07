"""
Repository — accès SQL brut pour le dashboard HR Analytics.

Responsabilité UNIQUE : exécuter des requêtes SQL et retourner des
lignes/dicts. Aucune logique métier ici (deltas, seuils, formatage) —
ça vit dans aggregator.py. Ce fichier ne fait que lire/écrire.

Deux sources de vérité distinctes :
  - jira.documents / servicenow.documents (metadata JSONB) : faits
    bruts sur les tickets, déjà ingérés par le pipeline RAG existant.
  - reports.employees / reports.ticket_scores : couche propre à cette
    feature (scores LLM pré-calculés, rattachement employé).
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HrAnalyticsRepository:

    # ── Lecture : faits bruts tickets (jira.documents / servicenow.documents) ──

    async def fetch_raw_tickets(
        self,
        session: AsyncSession,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> list[dict]:
        """
        Une ligne par ticket (Jira + ServiceNow réunis), avec les champs
        normalisés nécessaires au dashboard. Filtrage optionnel par
        période sur `created_at`.
        """
        query = text("""
            SELECT
                external_id                    AS ticket_id,
                'jira'                          AS source_type,
                metadata->>'status'             AS status,
                metadata->>'assignee'           AS assignee,
                metadata->>'created_at'         AS created_at,
                metadata->>'updated_at'         AS updated_at,
                metadata->>'resolved_at'        AS resolved_at
            FROM jira.documents
            WHERE (CAST(:period_start AS timestamptz) IS NULL OR (metadata->>'created_at')::timestamptz >= CAST(:period_start AS timestamptz))
              AND (CAST(:period_end AS timestamptz)   IS NULL OR (metadata->>'created_at')::timestamptz <  CAST(:period_end AS timestamptz))

            UNION ALL

            SELECT
                external_id                    AS ticket_id,
                'servicenow'                    AS source_type,
                metadata->>'state'              AS status,
                metadata->>'assigned_to'        AS assignee,
                metadata->>'created_at'         AS created_at,
                metadata->>'updated_at'         AS updated_at,
                metadata->>'resolved_at'        AS resolved_at
            FROM servicenow.documents
            WHERE (CAST(:period_start AS timestamptz) IS NULL OR (metadata->>'created_at')::timestamptz >= CAST(:period_start AS timestamptz))
              AND (CAST(:period_end AS timestamptz)   IS NULL OR (metadata->>'created_at')::timestamptz <  CAST(:period_end AS timestamptz))
        """)
        result = await session.execute(query, {
            "period_start": period_start,
            "period_end": period_end,
        })
        return [dict(row) for row in result.mappings().all()]

    # ── Lecture : scores LLM déjà calculés (reports.ticket_scores) ──

    async def fetch_ticket_scores(
        self,
        session: AsyncSession,
        ticket_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """Scores pré-calculés. Si `ticket_ids` est fourni, filtre dessus
        (utile pour joindre côté aggregator sans tout recharger)."""
        if ticket_ids is not None and not ticket_ids:
            return []

        query = text("""
            SELECT ticket_id, source_type, employee_id, is_closed,
                   resolution_hours, complexity_score, satisfaction_score,
                   llm_reasoning, prompt_version, scored_at
            FROM reports.ticket_scores
            WHERE (CAST(:ticket_ids AS text[]) IS NULL OR ticket_id = ANY(CAST(:ticket_ids AS text[])))
        """)
        result = await session.execute(query, {"ticket_ids": ticket_ids})
        return [dict(row) for row in result.mappings().all()]

    async def fetch_unscored_closed_tickets(
        self, session: AsyncSession, closed_statuses: list[str]
    ) -> list[dict]:
        """Utilisé par le job de scoring séparé (option B) : tickets
        fermés qui n'ont pas encore de ligne dans reports.ticket_scores."""
        query = text("""
            SELECT external_id AS ticket_id, 'jira' AS source_type,
                   title, metadata
            FROM jira.documents
            WHERE metadata->>'status' = ANY(:closed_statuses)
              AND external_id NOT IN (
                  SELECT ticket_id FROM reports.ticket_scores
                  WHERE source_type = 'jira'
              )

            UNION ALL

            SELECT external_id AS ticket_id, 'servicenow' AS source_type,
                   title, metadata
            FROM servicenow.documents
            WHERE metadata->>'state' = ANY(:closed_statuses)
              AND external_id NOT IN (
                  SELECT ticket_id FROM reports.ticket_scores
                  WHERE source_type = 'servicenow'
              )
        """)
        result = await session.execute(query, {"closed_statuses": closed_statuses})
        return [dict(row) for row in result.mappings().all()]

    async def fetch_ticket_full_content(
        self, session: AsyncSession, ticket_id: str, source_type: str
    ) -> str:
        """Concatène tous les chunks d'un ticket (body + commentaires),
        triés par chunk_id, pour donner au LLM le texte complet."""
        schema = "jira" if source_type == "jira" else "servicenow"
        query = text(f"""
            SELECT e.content
            FROM {schema}.embeddings e
            JOIN {schema}.documents d ON d.id = e.document_id
            WHERE d.external_id = :ticket_id
            ORDER BY e.chunk_id
        """)
        result = await session.execute(query, {"ticket_id": ticket_id})
        rows = result.scalars().all()
        return "\n\n".join(rows)

    # ── Écriture : reports.employees ──

    async def get_or_create_employee(
        self, session: AsyncSession, display_name: str
    ) -> str:
        """Rattachement provisoire par nom (pas d'auth encore). Retourne
        l'employee_id (UUID str)."""
        result = await session.execute(
            text("""
                INSERT INTO reports.employees (display_name)
                VALUES (:display_name)
                ON CONFLICT (display_name) DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING id
            """),
            {"display_name": display_name},
        )
        return str(result.scalar_one())

    # ── Écriture : reports.ticket_scores ──

    async def upsert_ticket_score(self, session: AsyncSession, score: dict) -> None:
        await session.execute(
            text("""
                INSERT INTO reports.ticket_scores (
                    ticket_id, source_type, employee_id, is_closed,
                    resolution_hours, complexity_score, satisfaction_score,
                    llm_reasoning, prompt_version
                ) VALUES (
                    :ticket_id, :source_type, :employee_id, :is_closed,
                    :resolution_hours, :complexity_score, :satisfaction_score,
                    :llm_reasoning, :prompt_version
                )
                ON CONFLICT (ticket_id, source_type) DO UPDATE SET
                    employee_id        = EXCLUDED.employee_id,
                    is_closed          = EXCLUDED.is_closed,
                    resolution_hours   = EXCLUDED.resolution_hours,
                    complexity_score   = EXCLUDED.complexity_score,
                    satisfaction_score = EXCLUDED.satisfaction_score,
                    llm_reasoning      = EXCLUDED.llm_reasoning,
                    prompt_version     = EXCLUDED.prompt_version,
                    scored_at          = now()
            """),
            score,
        )