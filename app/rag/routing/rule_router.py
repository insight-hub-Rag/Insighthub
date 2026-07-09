"""
Rule Router — premier filtre, sans aucun appel LLM.

Reconnaît par regex les identifiants explicites (ex: "IH-2") et route
directement en recherche par ID. Reconnaît par mots-clés les intentions
de filtre évidentes (statut, priorité) sans passer par le LLM Router.

Retourne None si la question est ambiguë — signal pour que le pipeline
passe la main au LLM Router.
"""

import logging
import re

from app.core.models import PreprocessedQuery, RoutingDecision

logger = logging.getLogger(__name__)

# Format générique des clés Jira : 2 à 10 lettres majuscules, tiret, chiffres.
# Couvre "IH-2", "PROJ-123", etc. sans dépendre d'un projet précis.
TICKET_ID_PATTERN = re.compile(r"\b([A-Z]{2,10}-\d+)\b")

STATUS_KEYWORDS = {
    "en cours": "En cours", "ouvert": "Open", "résolu": "Resolved",
    "fermé": "Closed", "terminé": "Done",
}
PRIORITY_KEYWORDS = {
    "urgent": "Highest", "critique": "Highest", "haute priorité": "High",
    "priorité basse": "Low",
}
SOURCE_KEYWORDS = {
    "jira": "jira", "ticket": "jira", "tickets": "jira",
    "confluence": "confluence", "page": "confluence", "pages": "confluence",
    "documentation": "confluence",
}


class RuleRouter:

    def route(self, query: PreprocessedQuery) -> RoutingDecision | None:
        text = query.cleaned_text
        text_lower = text.lower()

        # Cas 1 — identifiant explicite détecté (ex: "IH-2")
        match = TICKET_ID_PATTERN.search(text)
        if match:
            ticket_id = match.group(1)
            decision = RoutingDecision(
                sources=["jira"],  # les IDs de ce format sont des tickets Jira
                search_type="metadata",
                filters={"external_id": ticket_id},
                confidence=1.0,
                router_used="rule",
                reasoning=f"Identifiant détecté par regex : {ticket_id}",
            )
            logger.info(f"[RuleRouter] Cas simple (ID) → {decision}")
            return decision

        # Cas 2 — mots-clés de filtre évidents
        filters = {}
        for kw, value in STATUS_KEYWORDS.items():
            if kw in text_lower:
                filters["status"] = value
                break
        for kw, value in PRIORITY_KEYWORDS.items():
            if kw in text_lower:
                filters["priority"] = value
                break

        sources = {
            src for kw, src in SOURCE_KEYWORDS.items() if kw in text_lower
        }

        # On ne tranche en Rule Router que si au moins un signal clair
        # existe (filtre ou source explicite) — sinon on laisse la main
        # au LLM Router plutôt que de deviner.
        if not filters and not sources:
            logger.info("[RuleRouter] Aucun signal clair → délégation LLM Router")
            return None

        decision = RoutingDecision(
            sources=list(sources) if sources else ["jira", "confluence"],
            search_type="hybrid" if not filters else "metadata",
            filters=filters,
            confidence=0.9,
            router_used="rule",
            reasoning=f"Mots-clés détectés : filtres={filters}, sources={sources}",
        )
        logger.info(f"[RuleRouter] Cas simple (mots-clés) → {decision}")
        return decision