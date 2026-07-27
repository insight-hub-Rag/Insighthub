from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from config import settings


class ConfluenceClient:
    """
    Client HTTP bas niveau pour l'API REST Confluence Cloud (v2).
    Responsabilité unique : parler à l'API Confluence et streamer les pages
    brutes. Ne fait aucune transformation, ne connaît pas la structure
    métier qu'on en tirera ensuite (ça, c'est le rôle du transformer).

    Authentification identique à Jira : email + jeton API Atlassian
    
    """

    def __init__(
        self,
        url: Optional[str] = None,
        user: Optional[str] = None,
        api_token: Optional[str] = None,
        max_results: Optional[int] = None,
    ):
    
        # On travaille avec l'origine du site (sans /wiki). Les liens de
        # pagination renvoyés par l'API (_links.next) commencent déjà par
        # /wiki, donc on préfixe tout par l'origine seule pour éviter /wiki/wiki.
        origin = (url or settings.confluence_url).strip().rstrip("/")
        if origin.endswith("/wiki"):
            origin = origin[: -len("/wiki")]
        self.origin = origin
        self.auth = ((user or settings.confluence_user).strip(), (api_token or settings.confluence_api_token).strip())
        self.max_results = max_results or settings.confluence_max_results
        self.headers = {"Accept": "application/json"}

    async def fetch_all_pages(
        self, space_key: str, updated_after: Optional[str] = None
    ) -> AsyncGenerator[dict, None]:
       
        max_results = self.max_results
        total_fetched = 0

        logger.info(f"[Confluence] Début fetch | space={space_key}")

        async with httpx.AsyncClient() as client:
            space_id = await self._resolve_space_id(client, space_key)
            if space_id is None:
                logger.error(f"[Confluence] Espace introuvable : {space_key}")
                return

            next_path: Optional[str] = (
                f"/wiki/api/v2/spaces/{space_id}/pages"
                f"?body-format=storage&limit={max_results}"
            )

            while next_path:
                data = await self._fetch_path(client, next_path)
                for page in data.get("results", []):
                    yield page
                    total_fetched += 1
                next_path = (data.get("_links") or {}).get("next")

        logger.info(
            f"[Confluence] Fetch terminé | space={space_key} | total={total_fetched}"
        )

    async def test_connection(self) -> bool:
        """Vérifie que l'API Confluence est joignable avec les credentials configurés."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.origin}/wiki/api/v2/spaces",
                    params={"limit": 1},
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10,
                )
                resp.raise_for_status()
            logger.info(f"[Confluence] Connexion OK | instance={self.origin}")
            return True
        except Exception as e:
            logger.error(f"[Confluence] Connexion échouée : {e}")
            return False

    async def _resolve_space_id(
        self, client: httpx.AsyncClient, space_key: str
    ) -> Optional[str]:
        """
        L'API v2 des pages d'un espace attend l'ID numérique de l'espace,
        pas sa clé (ex: 'DOC'). On résout donc clé -> id au préalable.
        """
        resp = await client.get(
            f"{self.origin}/wiki/api/v2/spaces",
            params={"keys": space_key, "limit": 1},
            auth=self.auth,
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return str(results[0]["id"]) if results else None

    async def _fetch_path(self, client: httpx.AsyncClient, path: str) -> dict:
        """`path` est relatif (commence par /wiki...). On le préfixe par l'origine."""
        url = f"{self.origin}{path}"
        try:
            resp = await client.get(
                url, auth=self.auth, headers=self.headers, timeout=30
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Confluence] Erreur API (status={e.response.status_code}) "
                f"| path={path} : {e}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[Confluence] Erreur réseau | path={path} : {e}")
            raise
        return resp.json()