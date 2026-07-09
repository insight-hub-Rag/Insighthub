"""
Fusion Globale — combine les résultats de tous les agents (Jira,
Confluence...) en un classement unique.

Contrairement à la fusion interne d'un agent (qui combine SQL/Vector/
BM25 pour UNE source), celle-ci combine les listes déjà fusionnées de
CHAQUE agent — même algorithme RRF, appliqué à un niveau au-dessus.
"""

import logging

from app.core.models import AgentResult, RetrievedChunk
from app.rag.fusion.rrf import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def global_fusion(
    agent_results: list[AgentResult],
    top_k: int = 15,
) -> list[RetrievedChunk]:
    """
    Args:
        agent_results : résultats bruts de l'Agent Manager, un par
                        source interrogée (peut contenir des erreurs).
        top_k         : nombre de chunks finaux à conserver après
                        fusion, avant le reranking.

    Returns:
        Liste de RetrievedChunk triée par rrf_score décroissant,
        dédupliquée, prête pour le Cross-Encoder Reranker.
    """
    valid_results = []
    for result in agent_results:
        if result.error:
            logger.warning(
                f"[GlobalFusion] Agent '{result.source_type}' ignoré "
                f"(erreur : {result.error})"
            )
            continue
        if result.chunks:
            valid_results.append(result.chunks)

    if not valid_results:
        logger.warning("[GlobalFusion] Aucun agent n'a retourné de résultat")
        return []

    fused = reciprocal_rank_fusion(valid_results)
    final = fused[:top_k]

    sources_summary = ", ".join(
        f"{r.source_type}={len(r.chunks)}" for r in agent_results if not r.error
    )
    logger.info(
        f"[GlobalFusion] Entrées par agent : {sources_summary} | "
        f"{len(final)} chunks retenus après fusion globale"
    )
    return final