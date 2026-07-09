"""
Recherche BM25 approximatif — full-text search PostgreSQL natif.

Utilise la colonne générée `content_tsv` (tsvector) créée dans
postgres/init.sql, et `ts_rank` pour classer par pertinence lexicale.
Complète la recherche vectorielle : capte les correspondances de mots
exacts que le vector search peut manquer (ex: un identifiant, un terme
technique précis).
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


class BM25Retriever(BaseRetriever):

    def search(
        self,
        schema: str,
        query_text: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        if not query_text or not query_text.strip():
            return []

        conn = get_connection()
        try:
            if not schema_exists(conn, schema):
                return []

            with conn.cursor() as cur:
                # websearch_to_tsquery gère nativement les requêtes en
                # langage naturel (guillemets, "ou", négation avec -),
                # plus robuste que plainto_tsquery pour une question
                # utilisateur brute.
                cur.execute(
                    f"""
                    SELECT
                        e.chunk_id,
                        d.external_id,
                        d.title,
                        e.content,
                        e.metadata,
                        ts_rank(e.content_tsv, websearch_to_tsquery('french', %s)) AS rank
                    FROM {schema}.embeddings e
                    JOIN {schema}.documents d ON d.id = e.document_id
                    WHERE e.content_tsv @@ websearch_to_tsquery('french', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (query_text, query_text, top_k),
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
                    bm25_score=round(float(row[5]), 6),
                )
                for row in rows
            ]

            logger.info(
                f"[BM25Retriever] schema={schema} | query='{query_text[:50]}' | "
                f"{len(results)} chunks"
            )
            return results

        except Exception as e:
            logger.warning(f"[BM25Retriever] Schéma {schema} ignoré : {e}")
            return []

        finally:
            conn.close()