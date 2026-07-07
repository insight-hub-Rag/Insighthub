"""
Connecteur Confluence : implémentation concrète de BaseConnector pour la
source Confluence. Fait le pont entre ConfluenceClient (qui parle HTTP brut
à l'API Confluence v2) et le contrat générique attendu par IngestionPipeline.

C'est la seule classe Confluence-spécifique connue du pipeline générique —
le reste (client, transformer) est un détail d'implémentation interne.
"""

from typing import AsyncGenerator, Optional

from app.connectors.confluence.client import ConfluenceClient
from app.core.base_connector import BaseConnector
from app.core.models import RawRecord
from config import settings


class ConfluenceConnector(BaseConnector):

    def __init__(
        self,
        client: Optional[ConfluenceClient] = None,
        space_key: Optional[str] = None,
    ):
        """
        Args:
            client: instance de ConfluenceClient à utiliser. Si None, une
                    instance par défaut est créée à partir de la config.
                    Injectable pour les tests (on peut passer un mock).
            space_key: clé de l'espace Confluence à synchroniser. Si None,
                    utilise le premier espace configuré dans
                    settings.confluence_spaces.
        """
        self._client = client or ConfluenceClient()
        self._space_key = space_key or self._default_space_key()

    @property
    def source_type(self) -> str:
        return "confluence"

    @property
    def space_key(self) -> str:
        return self._space_key

    async def fetch(self, since: Optional[str] = None) -> AsyncGenerator[RawRecord, None]:
        async for page in self._client.fetch_all_pages(self._space_key, since):
            yield RawRecord(
                source_type=self.source_type,
                record_id=str(page["id"]),
                raw_data=page,
            )

    async def test_connection(self) -> bool:
        return await self._client.test_connection()

    @staticmethod
    def _default_space_key() -> str:
        if not settings.confluence_spaces:
            raise ValueError(
                "Aucune clé d'espace Confluence configurée. "
                "Définissez CONFLUENCE_SPACE_KEYS dans .env, ou passez "
                "space_key explicitement à ConfluenceConnector()."
            )
        return settings.confluence_spaces[0]
