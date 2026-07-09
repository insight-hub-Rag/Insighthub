"""
Context Builder — dernière étape avant la génération.

Sélectionne les chunks rerankés à envoyer réellement au LLM, en
respectant un budget de tokens approximatif (pour éviter de dépasser
la fenêtre de contexte du modèle et éviter de payer des tokens inutiles
sur des chunks à faible score).

Approximation volontairement simple : ~4 caractères par token pour le
français (pas de tokenizer exact chargé ici, pour rester léger — un
vrai compte de tokens serait plus précis mais ajoute une dépendance
supplémentaire pour un gain marginal à ce stade du projet).
"""

import logging

from app.core.models import RetrievedChunk

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_ESTIMATE = 4


def build_context(
    chunks: list[RetrievedChunk],
    max_tokens: int = 2000,
) -> list[RetrievedChunk]:
    """
    Args:
        chunks     : chunks déjà rerankés, triés par pertinence
                     décroissante (rerank_score).
        max_tokens : budget de tokens approximatif alloué au contexte
                     (le reste de la fenêtre sert au system prompt,
                     à la question, et à la réponse générée).

    Returns:
        Sous-liste de `chunks`, dans le même ordre, qui tient dans le
        budget de tokens estimé.
    """
    if not chunks:
        return []

    max_chars = max_tokens * CHARS_PER_TOKEN_ESTIMATE
    selected: list[RetrievedChunk] = []
    total_chars = 0

    for chunk in chunks:
        chunk_chars = len(chunk.content)
        if total_chars + chunk_chars > max_chars:
            # On s'arrête ici plutôt que de tronquer un chunk en plein
            # milieu — un chunk coupé produirait un contexte incohérent
            # pour le LLM.
            break
        selected.append(chunk)
        total_chars += chunk_chars

    logger.info(
        f"[ContextBuilder] {len(selected)}/{len(chunks)} chunks retenus | "
        f"~{total_chars // CHARS_PER_TOKEN_ESTIMATE} tokens estimés "
        f"(budget: {max_tokens})"
    )

    if not selected and chunks:
        # Cas limite : même le meilleur chunk seul dépasse le budget.
        # On le garde quand même tronqué plutôt que d'envoyer un
        # contexte vide au LLM.
        logger.warning(
            "[ContextBuilder] Premier chunk dépasse déjà le budget — troncature"
        )
        truncated = chunks[0]
        truncated.content = truncated.content[:max_chars]
        selected = [truncated]

    return selected