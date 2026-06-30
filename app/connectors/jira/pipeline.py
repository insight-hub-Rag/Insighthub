"""
Connecteur Jira : implémentation concrète de BaseConnector pour la source
Jira. Fait le pont entre JiraClient (qui parle HTTP brut à l'API Jira) et
le contrat générique attendu par IngestionPipeline.

C'est la seule classe Jira-spécifique connue du pipeline générique — tout
le reste (client, transformer) est un détail d'implémentation interne.
"""

from typing import AsyncGenerator, Optional

from app.connectors.jira.client import JiraClient
from app.core.base_connector import BaseConnector
from app.core.models import RawRecord
from config import settings


class JiraConnector(BaseConnector):

    def __init__(self, client: Optional[JiraClient] = None, project_key: Optional[str] = None):
        """
        Args:
            client: instance de JiraClient à utiliser. Si None, une instance
                    par défaut est créée à partir de la config (settings).
                    Injectable pour les tests (on peut passer un mock).
            project_key: clé du projet Jira à synchroniser. Si None, utilise
                    le premier projet configuré dans settings.jira_projects.
        """
        self._client = client or JiraClient()
        self._project_key = project_key or self._default_project_key()

    @property
    def source_type(self) -> str:
        return "jira"

    @property
    def project_key(self) -> str:
        return self._project_key

    async def fetch(self, since: Optional[str] = None) -> AsyncGenerator[RawRecord, None]:
        async for issue in self._client.fetch_all_issues(self._project_key, since):
            yield RawRecord(
                source_type=self.source_type,
                record_id=issue["key"],
                raw_data=issue,
            )

    async def test_connection(self) -> bool:
        return await self._client.test_connection()

    @staticmethod
    def _default_project_key() -> str:
        if not settings.jira_projects:
            raise ValueError(
                "Aucune clé de projet Jira configurée. "
                "Définissez JIRA_PROJECT_KEYS dans .env, ou passez "
                "project_key explicitement à JiraConnector()."
            )
        return settings.jira_projects[0]