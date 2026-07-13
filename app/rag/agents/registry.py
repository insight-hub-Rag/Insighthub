"""
Agent Registry — associe chaque nom de source à sa classe d'agent.

C'est le seul endroit du pipeline qui connaît la liste des sources
disponibles. L'Agent Manager ne fait que consulter ce registre — il ne
contient jamais de logique conditionnelle par source (if/elif), ce qui
garantit le principe Open/Closed : ajouter une source = une ligne ici,
zéro modification ailleurs.

ACTIVE_SOURCES contrôle quels agents sont réellement utilisables
aujourd'hui (données ingérées) — ServiceNow reste déclaré mais désactivé
tant que son ingestion n'existe pas, pour éviter que le router le
sélectionne pour rien.

NL2SQLAgent est un cas particulier : contrairement aux autres agents,
il n'a pas de constructeur sans argument (il a besoin d'une config de
connexion + de clients Bedrock) — il est donc construit via une factory
dédiée (build_nl2sql_agent) plutôt qu'instancié directement ici, mais
reste mis en cache de la même façon que les autres agents.
"""

import logging

from app.rag.agents.base_agent import BaseAgent
from app.rag.agents.jira_agent import JiraAgent
from app.rag.agents.confluence_agent import ConfluenceAgent
from app.rag.agents.sharepoint_agent import SharePointAgent
from app.rag.agents.servicenow_agent import ServiceNowAgent
from app.nl2sql.factory import build_nl2sql_agent

logger = logging.getLogger(__name__)

_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "jira": JiraAgent,
    "confluence": ConfluenceAgent,
    "sharepoint": SharePointAgent,
    "servicenow": ServiceNowAgent,
    # "sql" volontairement absent d'ici — voir get(), construit via factory.
}

# Sources réellement interrogeables aujourd'hui — à jour avec ce qui est
# ingéré. ServiceNow reste déclaré dans _AGENT_CLASSES (pour être prêt)
# mais absent d'ACTIVE_SOURCES tant qu'il n'y a pas de données.
ACTIVE_SOURCES = {"jira", "confluence", "sharepoint", "sql"}


class AgentRegistry:

    def __init__(self):
        self._instances: dict[str, BaseAgent] = {}

    def get(self, source_type: str) -> BaseAgent | None:
        """Retourne l'instance d'agent pour une source, ou None si la
        source est inconnue ou désactivée. Instances mises en cache
        (un seul agent par source pour toute la durée de vie de l'app)."""
        if source_type not in ACTIVE_SOURCES:
            logger.warning(
                f"[AgentRegistry] Source '{source_type}' inconnue ou "
                f"désactivée (actives : {ACTIVE_SOURCES})"
            )
            return None

        if source_type not in self._instances:
            if source_type == "sql":
                self._instances[source_type] = build_nl2sql_agent()
            else:
                agent_class = _AGENT_CLASSES[source_type]
                self._instances[source_type] = agent_class()

        return self._instances[source_type]

    def available_sources(self) -> list[str]:
        return sorted(ACTIVE_SOURCES)