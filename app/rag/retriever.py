import logging
from typing import Optional

import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

from config import settings
from app.core.models import SearchResult

logger = logging.getLogger(__name__)

# Sources disponibles et leurs schémas
SOURCES = {
    "jira":        "jira",
    "servicenow":  "servicenow",
    "sharepoint":  "sharepoint",
    "confluence":  "confluence",
}

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info(f"[Retriever] Chargement modèle : {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def _get_connection():
    conn = psycopg2.connect(settings.database_url_sync)
    register_vector(conn)
    return conn


class Retriever:
    """
    Recherche sémantique dans pgvector.
    Cherche dans toutes les sources actives ou une source spécifique.
    Retourne les top_k chunks les plus similaires à la question.
    """

    def search(
        self,
        query: str,
        source: Optional[str] = None,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
    ) -> list[SearchResult]:
        """
        Recherche les chunks les plus similaires à la question.

        Args:
            query:          question de l'utilisateur
            source:         filtrer par source ('jira', 'servicenow', etc.)
                           Si None, cherche dans toutes les sources
            top_k:          nombre de résultats à retourner
            min_similarity: seuil minimum de similarité cosine (0 à 1)

        Returns:
            Liste de SearchResult triés par similarité décroissante
        """
        top_k          = top_k or settings.rag_top_k
        min_similarity = min_similarity or settings.rag_min_similarity

        # 1. Embedder la question
        model     = _get_model()
        embedding = model.encode(
            query,
            normalize_embeddings=True,
        ).tolist()

        logger.info(
            f"[Retriever] Recherche | query='{query[:50]}' | "
            f"source={source or 'toutes'} | top_k={top_k}"
        )

        # 2. Choisir les sources à chercher
        sources_to_search = (
            {source: SOURCES[source]}
            if source and source in SOURCES
            else SOURCES
        )

        # 3. Chercher dans chaque source
        all_results = []
        conn = _get_connection()
        try:
            for source_type, schema in sources_to_search.items():
                results = self._search_in_schema(
                    conn, schema, source_type, embedding, top_k, min_similarity
                )
                all_results.extend(results)
        finally:
            conn.close()

        # 4. Trier par similarité et retourner top_k
        all_results.sort(key=lambda x: x.similarity, reverse=True)
        final = all_results[:top_k]

        logger.info(f"[Retriever] {len(final)} chunks trouvés")
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

            results = []
            for row in rows:
                chunk_id, doc_id, title, content, metadata, similarity = row
                results.append(SearchResult(
                    chunk_id    = chunk_id,
                    source_type = source_type,
                    document_id = doc_id,
                    content     = content,
                    title       = title or "",
                    similarity  = round(float(similarity), 4),
                    metadata    = metadata or {},
                ))
            return results

        except Exception as e:
            logger.warning(f"[Retriever] Erreur sur schéma {schema} : {e}")
            return []