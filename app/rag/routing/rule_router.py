"""
Rule Router — premier filtre, sans appel LLM, avant le LLM Router.

Principe directeur : chaque cas géré ici doit être fiable TOUT SEUL,
sans risque de faux-positif. Dès qu'un signal est ambigu pris isolément
(ex: "ticket" qui peut désigner un vrai ticket Jira OU une ligne de la
table SQL de démo `tickets`, ou "combien" qui apparaît dans n'importe
quelle question même hors scope), on ne tranche PAS ici : on retourne
None pour déléguer au LLM Router, seul capable de juger le sens réel
de la phrase et le scope (in_scope).

Cas couverts, du plus fiable au moins fiable :
  0. Question vide / uniquement des espaces                → in_scope=False, 1.0
  1. Identifiant explicite d'un projet CONNU (regex ciblé)  → jira, 1.0
  2. Salutation / politesse pure                             → in_scope=False, 0.95
  3. Nom de source cité explicitement (jira/confluence/...)   → source, 0.9
  4. Nom de domaine métier fort (employés/salaire/congé...)   → sql, 0.85
  Sinon (mots génériques, ambiguïtés, tout le reste)          → None (délégation LLM Router)
"""

import logging
import re

from config import settings
from app.core.models import PreprocessedQuery, RoutingDecision

logger = logging.getLogger(__name__)


def _build_ticket_id_pattern() -> re.Pattern:
    """
    Construit le regex d'identifiant à partir des clés de projet
    RÉELLEMENT configurées (settings.jira_projects, ex: INFRA, DEV,
    SUPPORT, SEC — cf. écran Connecteurs).

    Pourquoi pas un pattern générique [A-Z]{2,10}-\\d+ : il matche aussi
    "COVID-19", "RGPD-2016", "H1N1-2009"... n'importe quel sigle suivi
    d'un tiret et d'un nombre est accepté par ce format, hors scope ou
    pas. En n'acceptant que les clés de projet réellement synchronisées,
    ce faux-positif disparaît complètement.

    Fallback sur le pattern générique uniquement si aucune clé n'est
    configurée (ex: environnement de test) — mieux vaut un léger risque
    de faux-positif que de ne jamais reconnaître aucun ID.
    """
    projects = settings.jira_projects
    if projects:
        alternation = "|".join(re.escape(p) for p in projects)
        return re.compile(rf"\b(({alternation})-\d+)\b")
    return re.compile(r"\b([A-Z]{2,10}-\d+)\b")



# --- Cas 2 : salutations / politesse pure -------------------------------
# Fiable seulement si la phrase ENTIÈRE (nettoyée) ne contient QUE ça —
# "bonjour, combien de congés en attente ?" ne doit PAS matcher ce cas,
# seulement "bonjour" ou "merci beaucoup !" tout seuls.
GREETING_WORDS = {
    "bonjour", "bonsoir", "salut", "coucou", "hello", "hi",
    "merci", "merci beaucoup", "au revoir", "bye", "ça va", "cava",
}

# --- Cas 3 : nom de source cité explicitement ---------------------------
# Uniquement les noms de PRODUIT, jamais un nom commun ambigu comme
# "ticket" ou "page" (trop générique, cf. docstring module).
SOURCE_NAME_KEYWORDS = {
    "jira": "jira",
    "confluence": "confluence",
    "sharepoint": "sharepoint",
}

# --- Cas 4 : noms de domaine métier forts -------------------------------
# Risque résiduel documenté : une question générale contenant "salaire"
# (ex: "salaire moyen d'un dev en France") matchera quand même "sql".
# Compromis assumé — reste un cas beaucoup plus rare que les opérateurs
# génériques (combien/total), qu'on a délibérément exclus d'ici.
SQL_DOMAIN_NOUNS = {"employés", "salaire", "congé", "congés"}

# Mots qui évoquent une intention de filtre par statut/priorité — PAS
# un dictionnaire de mapping vers une valeur exacte. Un dictionnaire
# figé ("urgent" -> "Highest") ne peut jamais couvrir tous les
# synonymes ("important", "prioritaire", "à traiter en premier"...) ni
# choisir la bonne échelle réelle (Highest vs High) selon le contexte.
# Dès qu'un de ces mots apparaît à côté d'une source explicite, on ne
# tranche PLUS ici : on délègue tout au LLM Router, qui connaît déjà
# les vraies valeurs d'énumération (cf llm_router.py) et peut
# interpréter n'importe quelle formulation, pas seulement celles listées
# ci-dessous.
STATUS_HINT_WORDS = {
    "statut", "état", "en cours", "en traitement", "à faire", "a faire",
    "pas commencé", "terminé", "terminés", "fini", "finis", "fait", "faits",
    "résolu", "résolus", "résolue", "résolues", "non résolu", "non résolus",
    "irrésolu", "irrésolus", "pas résolu", "pas résolus",
}
PRIORITY_HINT_WORDS = {
    "urgent", "urgents", "priorité", "priorite", "critique", "critiques",
    "important", "importants", "mineur", "mineurs", "haute priorité",
    "priorité basse",
}

# Mots qui, à eux seuls, rendent un cas trop ambigu pour trancher ici
# (utilisés pour EXCLURE le cas 2 même si une salutation est présente).
AMBIGUOUS_STANDALONE_WORDS = ("ticket", "tickets")


def _word_in(word: str, text: str) -> bool:
    """Match sur un mot entier (frontières \\b), pas une sous-chaîne —
    évite qu'un mot-clé matche à l'intérieur d'un autre mot par hasard."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _has_filter_intent(text_lower: str) -> bool:
    """Détecte la simple PRÉSENCE d'une intention de filtre (statut ou
    priorité), sans essayer de deviner la valeur exacte — c'est au LLM
    Router de le faire, lui seul comprend le contexte."""
    return any(
        _word_in(kw, text_lower) for kw in (*STATUS_HINT_WORDS, *PRIORITY_HINT_WORDS)
    )


class RuleRouter:

    def __init__(self):
        # Construit à l'instanciation (pas au chargement du module) pour
        # rester testable : les tests peuvent créer un RuleRouter() après
        # avoir simulé une config différente de settings.jira_project_keys.
        self.ticket_id_pattern = _build_ticket_id_pattern()

    def route(self, query: PreprocessedQuery) -> RoutingDecision | None:
        text = query.cleaned_text
        text_lower = text.lower().strip(" !?.,")

        # --- Cas 0 : question vide ou uniquement des espaces -----------
        # Signal 100% fiable, et surtout indispensable : Bedrock (via
        # converse()) rejette un ContentBlock avec un texte vide
        # (ValidationException) — il ne faut jamais laisser une question
        # vide atteindre le LLM Router, quel que soit le backend.
        if not text.strip():
            decision = RoutingDecision(
                sources=[],
                search_type="hybrid",
                filters={},
                confidence=1.0,
                router_used="rule",
                reasoning="Question vide ou blanche",
                in_scope=False,
            )
            logger.info(f"[RuleRouter] Cas 0 (question vide) → {decision}")
            return decision

        # --- Cas 1 : identifiant explicite d'un projet connu -----------
        match = self.ticket_id_pattern.search(text)
        if match:
            ticket_id = match.group(1)
            decision = RoutingDecision(
                sources=["jira"],
                search_type="metadata",
                filters={"external_id": ticket_id},
                confidence=1.0,
                router_used="rule",
                reasoning=f"Identifiant de projet connu détecté : {ticket_id}",
                in_scope=True,
            )
            logger.info(f"[RuleRouter] Cas 1 (ID) → {decision}")
            return decision

        # --- Cas 2 : salutation / politesse pure ------------------------
        # On ne matche que si la phrase nettoyée est ENTIÈREMENT un mot
        # de politesse (ou très proche) — pas juste "contient".
        if text_lower in GREETING_WORDS or (
            len(text_lower.split()) <= 3
            and any(g in text_lower for g in GREETING_WORDS)
            and not any(
                _word_in(kw, text_lower)
                for kw in (*SOURCE_NAME_KEYWORDS, *SQL_DOMAIN_NOUNS, *AMBIGUOUS_STANDALONE_WORDS)
            )
        ):
            decision = RoutingDecision(
                sources=[],
                search_type="hybrid",
                filters={},
                confidence=0.95,
                router_used="rule",
                reasoning="Salutation/politesse pure détectée",
                in_scope=False,
            )
            logger.info(f"[RuleRouter] Cas 2 (salutation) → {decision}")
            return decision

        # --- Cas 3 : nom de source cité explicitement --------------------
        source_hit = next(
            (src for kw, src in SOURCE_NAME_KEYWORDS.items() if _word_in(kw, text_lower)),
            None,
        )
        if source_hit:
            if _has_filter_intent(text_lower):
                # Une intention de filtre est présente (statut/priorité,
                # sous n'importe quelle formulation) — deviner la bonne
                # valeur ("urgent" = Highest ? High ? ça dépend du
                # contexte réel) n'est PAS fiable ici. On délègue tout
                # au LLM Router, qui connaît les vraies valeurs
                # d'énumération et comprend n'importe quel synonyme.
                logger.info(
                    f"[RuleRouter] Source '{source_hit}' explicite mais "
                    "intention de filtre détectée → délégation LLM Router "
                    "pour interpréter la bonne valeur"
                )
                return None

            decision = RoutingDecision(
                sources=[source_hit],
                search_type="hybrid",
                filters={},
                confidence=0.9,
                router_used="rule",
                reasoning=f"Nom de source cité explicitement : {source_hit}",
                in_scope=True,
            )
            logger.info(f"[RuleRouter] Cas 3 (source explicite) → {decision}")
            return decision

        # --- Cas 4 : nom de domaine métier fort ---------------------------
        if any(_word_in(kw, text_lower) for kw in SQL_DOMAIN_NOUNS):
            decision = RoutingDecision(
                sources=["sql"],
                search_type="hybrid",
                filters={},
                confidence=0.85,
                router_used="rule",
                reasoning="Nom de domaine métier fort détecté (RH/business)",
                in_scope=True,
            )
            logger.info(f"[RuleRouter] Cas 4 (domaine métier) → {decision}")
            return decision

        # --- Sinon : ambigu → délégation LLM Router -----------------------
        logger.info("[RuleRouter] Aucun cas fiable → délégation LLM Router")
        return None