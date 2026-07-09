"""
Recherche SQL directe sur les métadonnées (JSONB) — cherche dans UN
schéma à la fois, sans calcul de similarité. Utilisée quand le router
(Rule Router ou LLM Router) a détecté un filtre exact plutôt qu'une
question sémantique ouverte (ex: "tickets en cours", "priorité haute"),
ou un identifiant natif explicite (ex: "IH-2").

Score toujours à 1.0 : un filtre exact n'a pas de notion de "à quel
point c'est pertinent" — soit ça matche, soit ça matche pas.
"""

import logging
from typing import Optional

from app.core.models import RetrievedChunk
from app.rag.retrievers.base_retriever import (
    BaseRetriever,
    get_connection,
    schema_exists,
)

logger = logging.getLogger(__name__)

# Clés de metadata autorisées au filtrage, par schéma — confirmées
# depuis les transformers réels (JiraTransformer, ConfluenceTransformer,
# SharePointTransformer). Whitelist volontaire : on ne construit jamais
# une clause SQL à partir d'une clé arbitraire fournie par le LLM Router,
# pour éviter tout risque d'injection ou de filtre sur un champ inexistant.
#
# NOTE : pas de connecteur ServiceNow dans ce projet pour l'instant
# (ni app/connectors/servicenow/, ni schéma ingéré) — pas d'entrée ici
# tant qu'il n'existe pas réellement.
ALLOWED_FILTER_KEYS = {
    "jira":       {"status", "priority", "assignee", "issue_type", "comment_author"},
    "confluence": {"space_id", "status", "version"},
    "sharepoint": {"list_title", "author", "editor", "file_ref"},
}


class SQLRetriever(BaseRetriever):

    def search(
        self,
        schema: str,
        query_text: str = "",
        top_k: int = 20,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        if not filters:
            return []

        allowed = ALLOWED_FILTER_KEYS.get(schema, set())
        safe_filters = {k: v for k, v in filters.items() if k in allowed and v}

        if not safe_filters:
            logger.warning(
                f"[SQLRetriever] Aucun filtre valide pour schema={schema} "
                f"(reçu: {list(filters.keys())}, autorisé: {allowed})"
            )
            return []

        conn = get_connection()
        try:
            if not schema_exists(conn, schema):
                return []

            where_clauses = []
            params: list = []
            for key, value in safe_filters.items():
                where_clauses.append("e.metadata->>%s ILIKE %s")
                params.extend([key, f"%{value}%"])

            where_sql = " AND ".join(where_clauses)
            params.append(top_k)

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        e.chunk_id,
                        d.external_id,
                        d.title,
                        e.content,
                        e.metadata
                    FROM {schema}.embeddings e
                    JOIN {schema}.documents d ON d.id = e.document_id
                    WHERE {where_sql}
                    ORDER BY e.created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()

            results = [
                RetrievedChunk(
                    source_type=schema,
                    document_id=row[1],
                    chunk_id=row[0],
                    content=row[3],
                    title=row[2] or "",
                    metadata=row[4] or {},
                    sql_score=1.0,
                )
                for row in rows
            ]

            logger.info(
                f"[SQLRetriever] schema={schema} | filtres={safe_filters} | "
                f"{len(results)} chunks"
            )
            return results

        except Exception as e:
            logger.warning(f"[SQLRetriever] Schéma {schema} ignoré : {e}")
            return []

        finally:
            conn.close()

    def search_by_id(self, schema: str, external_id: str) -> list[RetrievedChunk]:
        """
        Recherche directe par identifiant natif (ex: 'IH-2'), pas par
        filtre metadata. Utilisée par le Rule Router quand la question
        contient un ID reconnu par regex — match exact garanti, score 1.0.
        """
        conn = get_connection()
        try:
            if not schema_exists(conn, schema):
                return []

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT e.chunk_id, d.external_id, d.title, e.content, e.metadata
                    FROM {schema}.embeddings e
                    JOIN {schema}.documents d ON d.id = e.document_id
                    WHERE d.external_id = %s
                    ORDER BY e.chunk_id
                    """,
                    (external_id,),
                )
                rows = cur.fetchall()

            return [
                RetrievedChunk(
                    source_type=schema,
                    document_id=row[1],
                    chunk_id=row[0],
                    content=row[3],
                    title=row[2] or "",
                    metadata=row[4] or {},
                    sql_score=1.0,
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning(f"[SQLRetriever] search_by_id échoué sur {schema} : {e}")
            return []

        finally:
            conn.close()