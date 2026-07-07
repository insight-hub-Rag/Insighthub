import logging
import time
from typing import Optional

import psycopg2
from pgvector.psycopg2 import register_vector

from config import settings
from app.core.models import Chunk, SearchResult

logger = logging.getLogger(__name__)

SOURCES = {
    "jira":        "jira",
    "servicenow":  "servicenow",
    "sharepoint":  "sharepoint",
    "confluence":  "confluence",
}

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from app.ingestion.embeddings.embedder import Embedder
        _embedder = Embedder()
    return _embedder


def _get_connection():
    conn = psycopg2.connect(settings.database_url_sync)
    register_vector(conn)
    return conn


class Retriever:

    def search(
        self,
        query: str,
        source: Optional[str] = None,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
    ) -> list[SearchResult]:
        top_k          = top_k or settings.rag_top_k
        min_similarity = min_similarity or settings.rag_min_similarity

        # Embedding de la question
        t0         = time.time()
        embedder   = _get_embedder()
        temp_chunk = Chunk(
            chunk_id    = "query",
            document_id = "query",
            source_type = "query",
            content     = query,
        )
        embedder.embed_chunks([temp_chunk])
        embedding = temp_chunk.embedding
        t_embed   = time.time() - t0

        # Recherche pgvector
        t1 = time.time()
        sources_to_search = (
            {source: SOURCES[source]}
            if source and source in SOURCES
            else SOURCES
        )

        all_results = []
        conn        = _get_connection()
        try:
            for source_type, schema in sources_to_search.items():
                results = self._search_in_schema(
                    conn, schema, source_type,
                    embedding, top_k, min_similarity,
                )
                all_results.extend(results)
        finally:
            conn.close()

        t_search = time.time() - t1
        t_total  = time.time() - t0

        all_results.sort(key=lambda x: x.similarity, reverse=True)
        final = all_results[:top_k]

        logger.info(
            f"[Retriever] {len(final)} chunks | "
            f"embed={t_embed*1000:.1f}ms | "
            f"search={t_search*1000:.1f}ms | "
            f"total={t_total*1000:.1f}ms"
        )
        return final

    def _search_in_schema(
        self,
        conn,
        schema: str,
        source_type: str,
        embedding: list,
        top_k: int,
        min_similarity: float,
    ) -> list[SearchResult]:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s
                        AND table_name = 'embeddings'
                    )
                """, (schema,))
                if not cur.fetchone()[0]:
                    return []

                cur.execute(f"""
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
                """, (embedding, embedding, min_similarity, embedding, top_k))

                rows = cur.fetchall()

            return [
                SearchResult(
                    chunk_id    = row[0],
                    source_type = source_type,
                    document_id = row[1],
                    content     = row[3],
                    title       = row[2] or "",
                    similarity  = round(float(row[5]), 4),
                    metadata    = row[4] or {},
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning(f"[Retriever] Schéma {schema} ignoré : {e}")
            return []