"""
Reciprocal Rank Fusion (RRF).

Combine plusieurs listes déjà triées (par score décroissant) en un seul
classement cohérent. Utilisé à deux niveaux dans le pipeline :
  1. Fusion interne d'un agent : combine SQL + Vector + BM25 pour UNE source.
  2. Fusion globale : combine les résultats de TOUS les agents (Jira,
     ServiceNow, Confluence...) en un classement unique.

Principe : plus un chunk est bien classé dans plusieurs listes,
plus son score RRF final est élevé. Pas besoin d'entraînement,
formule simple et robuste, standard en recherche d'information.
"""

from app.core.models import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    k: int = 60,
) -> list[RetrievedChunk]:
    """
    Args:
        ranked_lists : plusieurs listes de RetrievedChunk, chacune déjà
                       triée par pertinence décroissante (ex: [résultats_sql,
                       résultats_vector, résultats_bm25]).
        k            : constante de lissage RRF (60 = valeur standard
                       dans la littérature, évite qu'un rang 1 écrase
                       tout le reste).

    Returns:
        Une seule liste de RetrievedChunk, dédupliquée par identité de
        chunk, triée par score RRF décroissant, avec `rrf_score` rempli
        sur chaque chunk.
    """
    scores: dict[str, float] = {}
    chunks_by_key: dict[str, RetrievedChunk] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            key = _chunk_key(chunk)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

            # On garde le chunk avec le plus d'infos (le premier vu,
            # les scores individuels sql/vector/bm25 sont déjà dessus)
            if key not in chunks_by_key:
                chunks_by_key[key] = chunk
            else:
                _merge_method_scores(chunks_by_key[key], chunk)

    fused: list[RetrievedChunk] = []
    for key, score in scores.items():
        chunk = chunks_by_key[key]
        chunk.rrf_score = round(score, 6)
        fused.append(chunk)

    fused.sort(key=lambda c: c.rrf_score, reverse=True)
    return fused


def _chunk_key(chunk: RetrievedChunk) -> str:
    """Identité unique d'un chunk, indépendante de la méthode qui l'a trouvé."""
    return f"{chunk.source_type}:{chunk.document_id}:{chunk.chunk_id}"


def _merge_method_scores(target: RetrievedChunk, other: RetrievedChunk) -> None:
    """
    Quand le même chunk apparaît dans plusieurs listes (ex: trouvé à la
    fois par vector ET bm25), on fusionne leurs scores individuels sur
    un seul objet plutôt que d'en garder un et perdre l'info de l'autre.
    """
    if other.sql_score is not None:
        target.sql_score = other.sql_score
    if other.vector_score is not None:
        target.vector_score = other.vector_score
    if other.bm25_score is not None:
        target.bm25_score = other.bm25_score