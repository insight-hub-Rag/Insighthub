import asyncio
from typing import Any, Iterable, List, Optional

from loguru import logger
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.caml.caml_query import CamlQuery

from config import settings


class SharePointClient:
    """
    Client SharePoint bas niveau pour récupérer des éléments de liste.

    Les appels sont synchrones via Office365-REST-Python-Client, mais le
    connecteur expose une interface async pour rester compatible avec le
    pipeline existant.
    """

    def __init__(self):
        self.site_url = settings.sharepoint_site_url.rstrip("/")
        self.credential = ClientCredential(
            settings.sharepoint_client_id,
            settings.sharepoint_client_secret,
        )
        self._ctx = ClientContext(self.site_url).with_credentials(self.credential)

    async def fetch_all_items(
        self, list_title: str, updated_after: Optional[str] = None
    ) -> Any:
        items = await asyncio.to_thread(
            self._get_items,
            list_title,
            updated_after,
        )
        for item in items:
            yield item

    async def test_connection(self) -> bool:
        return await asyncio.to_thread(self._test_connection_sync)

    def _get_items(self, list_title: str, updated_after: Optional[str]) -> List[dict]:
        query = CamlQuery()
        if updated_after:
            query.ViewXml = (
                "<View>"
                "<Query>"
                "<Where>"
                "<Geq>"
                "<FieldRef Name='Modified' />"
                "<Value IncludeTimeValue='TRUE' Type='DateTime'>"
                f"{updated_after}"
                "</Value>"
                "</Geq>"
                "</Where>"
                "<OrderBy><FieldRef Name='Modified' Ascending='TRUE' /></OrderBy>"
                "</Query>"
                "</View>"
            )

        sharepoint_list = self._ctx.web.lists.get_by_title(list_title)
        items = sharepoint_list.get_items(query)
        self._ctx.load(items)
        self._ctx.execute_query()

        results: List[dict] = []
        for item in items:  # type: ignore[attr-defined]
            results.append(item.properties)

        logger.info(
            f"[SharePoint] Fetch terminé | list={list_title} | total={len(results)}"
        )
        return results

    def _test_connection_sync(self) -> bool:
        try:
            web = self._ctx.web
            self._ctx.load(web)
            self._ctx.execute_query()
            logger.info(f"[SharePoint] Connexion OK | site={self.site_url}")
            return True
        except Exception as exc:
            logger.error(f"[SharePoint] Connexion échouée : {exc}")
            return False
