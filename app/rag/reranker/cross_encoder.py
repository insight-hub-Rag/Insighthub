"""
Cross-Encoder Reranker — étape la plus impactante du pipeline en
termes de précision finale.

Contrairement aux retrievers (bi-encoder : question et chunk encodés
séparément), le cross-encoder lit la question ET le chunk ensemble
dans un seul passage — bien plus précis pour juger la pertinence
réelle, au prix d'un calcul plus lourd (donc appliqué seulement aux
quelques dizaines de candidats sortis de la fusion globale, jamais à
toute la base).

Modèle multilingue (mmarco) car le contenu est en français.
"""

import logging

from app.core.models import RetrievedChunk

logger = logging.getLogger(__name__)

_model = None
_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        logger.info(f"[Reranker] Chargement du modèle : {_MODEL_NAME}")
        _model = CrossEncoder(_MODEL_NAME)
    return _model


class CrossEncoderReranker:

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_n: int = 8,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        model = _get_model()
        pairs = [(query, chunk.content) for chunk in chunks]

        scores = model.predict(pairs)

        for chunk, score in zip(chunks, scores):
            chunk.rerank_score = round(float(score), 6)

        reranked = sorted(chunks, key=lambda c: c.rerank_score, reverse=True)
        top_chunks = reranked[:top_n]

        logger.info(
            f"[Reranker] {len(chunks)} candidats → {len(top_chunks)} retenus | "
            f"meilleur score={top_chunks[0].rerank_score if top_chunks else 'N/A'}"
        )
        return top_chunks