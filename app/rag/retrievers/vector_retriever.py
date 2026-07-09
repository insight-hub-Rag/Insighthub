"""
Recherche vectorielle (pgvector) — cherche dans UN schéma à la fois.

Repris de l'ancien app/rag/retriever.py, mais adapté au contrat
BaseRetriever : chaque agent (JiraAgent, ServiceNowAgent...) appelle
ce retriever avec SON schéma, plutôt que ce retriever ne boucle
lui-même sur toutes les sources.
"""

import logging
import time
from typing import Optional

from app.core.models import Chunk, RetrievedChunk
from app.rag.retrievers.base_retriever import (
    BaseRetriever,
    get_connection,
    schema_exists,
)

logger = logging.getLogger(__name__)

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from app.ingestion.embeddings.embedder import Embedder
        _embedder = Embedder()
    return _embedder


def embed_query(query_text: str) -> list[float]:
    """
    Calcule l'embedding d'une question. Séparé en fonction propre pour
    que le Query Preprocessor ou un agent puisse le calculer UNE fois
    et le réutiliser pour plusieurs retrievers, plutôt que de le
    recalculer à chaque appel (coûteux).
    """
    embedder = _get_embedder()
    temp_chunk = Chunk(
        chunk_id="query",
        document_id="query",
        source_type="query",
        content=query_text,
    )
    embedder.embed_chunks([temp_chunk])
    return temp_chunk.embedding


class VectorRetriever(BaseRetriever):

    def search(
        self,
        schema: str,
        query_text: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
        query_embedding: Optional[list[float]] = None,
        min_similarity: Optional[float] = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        from config import settings

        min_similarity = min_similarity if min_similarity is not None else settings.rag_min_similarity

        t0 = time.time()
        embedding = query_embedding or embed_query(query_text)
        t_embed = time.time() - t0

        conn = get_connection()
        try:
            if not schema_exists(conn, schema):
                return []

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        e.chunk_id,
                        d.external_id,
                        d.title,
                        e.content,
                        e.metadata,
                        1 - (e.embedding <=> %s::vector) AS similarity
                    FROM {schema}.embeddings e
                    JOIN {schema}.documents d ON d.id = e.document_id
                    WHERE 1 - (e.embedding <=> %s::vector) >= %s
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (embedding, embedding, min_similarity, embedding, top_k),
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
                    vector_score=round(float(row[5]), 4),
                )
                for row in rows
            ]

            logger.info(
                f"[VectorRetriever] schema={schema} | {len(results)} chunks | "
                f"embed={t_embed*1000:.1f}ms"
            )
            return results

        except Exception as e:
            logger.warning(f"[VectorRetriever] Schéma {schema} ignoré : {e}")
            return []

        finally:
            conn.close()