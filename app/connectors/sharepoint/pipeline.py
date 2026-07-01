from typing import AsyncGenerator, Optional

from app.connectors.sharepoint.client import SharePointClient
from app.core.base_connector import BaseConnector
from app.core.models import RawRecord
from config import settings


class SharePointConnector(BaseConnector):

    def __init__(
        self,
        client: Optional[SharePointClient] = None,
        list_title: Optional[str] = None,
    ):
        self._client = client or SharePointClient()
        self._list_title = list_title or self._default_list_title()

    @property
    def source_type(self) -> str:
        return "sharepoint"

    @property
    def list_title(self) -> str:
        return self._list_title

    async def fetch(self, since: Optional[str] = None) -> AsyncGenerator[RawRecord, None]:
        async for item in self._client.fetch_all_items(self._list_title, since):
            record_id = str(item.get("Id") or item.get("GUID") or item.get("UniqueId") or "")
            yield RawRecord(
                source_type=self.source_type,
                record_id=record_id,
                raw_data=item,
            )

    async def test_connection(self) -> bool:
        return await self._client.test_connection()

    @staticmethod
    def _default_list_title() -> str:
        if not settings.sharepoint_list_title:
            raise ValueError(
                "Aucun nom de liste SharePoint configuré. "
                "Définissez SHAREPOINT_LIST_TITLE dans .env, ou passez "
                "list_title explicitement à SharePointConnector()."
            )
        return settings.sharepoint_list_title
