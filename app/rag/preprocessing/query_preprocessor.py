"""
Query Preprocessor — première étape du pipeline, avant tout routage.

Nettoie la question brute de l'utilisateur (espaces, caractères de
contrôle) et détecte la langue (français par défaut, anglais si détecté)
pour que le full-text search (BM25) utilise la bonne configuration
PostgreSQL ('french' vs 'english' dans to_tsvector/websearch_to_tsquery).

Pas d'historique de conversation géré ici pour l'instant — chaque
question est traitée de façon autonome (pas de chat multi-tour dans
ce projet à ce stade).
"""

import logging
import re

from app.core.models import PreprocessedQuery

logger = logging.getLogger(__name__)

# Mots très fréquents et discriminants entre les deux langues.
# Heuristique volontairement simple : suffisant pour distinguer fr/en
# sur une question courte, sans dépendance externe (pas de langdetect
# dans requirements.txt). Si besoin de plus robuste plus tard :
# `pip install langdetect` puis remplacer _detect_language() par
# `from langdetect import detect`.
_FRENCH_MARKERS = {
    "le", "la", "les", "un", "une", "des", "du", "de", "est", "sont",
    "quel", "quelle", "quels", "comment", "pourquoi", "qui", "que",
    "combien", "où", "avec", "pour", "dans", "sur",
}
_ENGLISH_MARKERS = {
    "the", "a", "an", "is", "are", "what", "how", "why", "who",
    "which", "when", "where", "with", "for", "in", "on",
}


def _clean_text(text: str) -> str:
    """Normalise espaces multiples, retours à la ligne, caractères de
    contrôle invisibles. Ne touche pas à la ponctuation ni aux accents
    (utiles pour le full-text search et le LLM)."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)  # contrôle
    text = re.sub(r"\s+", " ", text)  # espaces/retours multiples
    return text.strip()


def _detect_language(cleaned_text: str) -> str:
    """Retourne 'fr' ou 'en' selon les mots fonctionnels présents.
    Défaut 'fr' en cas d'égalité ou de texte trop court pour trancher —
    cohérent avec l'audience principale du projet."""
    words = set(re.findall(r"[a-zàâäéèêëïîôöùûüç]+", cleaned_text.lower()))
    fr_hits = len(words & _FRENCH_MARKERS)
    en_hits = len(words & _ENGLISH_MARKERS)
    return "en" if en_hits > fr_hits else "fr"


class QueryPreprocessor:

    def run(self, raw_text: str, user_id: str | None = None) -> PreprocessedQuery:
        cleaned = _clean_text(raw_text)
        language = _detect_language(cleaned)

        logger.info(
            f"[QueryPreprocessor] lang={language} | "
            f"'{raw_text[:60]}' → '{cleaned[:60]}'"
        )

        return PreprocessedQuery(
            original_text=raw_text,
            cleaned_text=cleaned,
            language=language,
            user_id=user_id,
        )