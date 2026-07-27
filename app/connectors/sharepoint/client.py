import asyncio
from typing import Any, List, Optional

from loguru import logger

from config import settings


class SharePointClient:
  
  

    def __init__(
        self,
        site_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
      
        self.site_url = (site_url or settings.sharepoint_site_url).strip().rstrip("/")
        _client_id = client_id or settings.sharepoint_client_id
        _client_secret = client_secret or settings.sharepoint_client_secret

        # Lazy import of Office365 library so the application can start
        # even if the dependency is missing in the runtime (useful during
        # iterative development). If the package is not available the
        # methods that actually access SharePoint will raise a clear error
        # explaining the required action (install dependency / rebuild image).
        try:
            from office365.runtime.auth.client_credential import ClientCredential
            from office365.sharepoint.client_context import ClientContext
        except Exception:
            self._ctx = None
            self._credential = None
            return

        self._credential = ClientCredential(_client_id, _client_secret)
        self._ctx = ClientContext(self.site_url).with_credentials(self._credential)

    async def fetch_all_items(
        self, list_title: str, updated_after: Optional[str] = None
    ) -> Any:
        if self._ctx is None:
            raise RuntimeError(
                "Office365 library not available in runtime. "
                "Install 'Office365-REST-Python-Client' and rebuild the Docker image."
            )

        items = await asyncio.to_thread(self._get_items, list_title, updated_after)
        for item in items:
            yield item

    async def test_connection(self) -> bool:
        if self._ctx is None:
            raise RuntimeError(
                "Office365 library not available in runtime. "
                "Install 'Office365-REST-Python-Client' and rebuild the Docker image."
            )
        return await asyncio.to_thread(self._test_connection_sync)

    def _get_items(self, list_title: str, updated_after: Optional[str]) -> List[dict]:
      
        try:
            from office365.sharepoint.caml.caml_query import CamlQuery
        except Exception:
            CamlQuery = None

        query = None
        if CamlQuery is not None:
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
        if query is not None:
            items = sharepoint_list.get_items(query)
        else:
            items = sharepoint_list.items

        self._ctx.load(items)
        self._ctx.execute_query()

        results: List[dict] = []
        for item in items:  # type: ignore[attr-defined]
            props = item.properties
            # If updated_after was provided but CAML isn't available, filter
            # client-side.
            if updated_after and CamlQuery is None:
                modified = props.get("Modified")
                if modified and str(modified) < str(updated_after):
                    continue
            results.append(props)

        logger.info(f"[SharePoint] Fetch terminé | list={list_title} | total={len(results)}")
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