from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from config import settings


class JiraClient:
    

    def __init__(
        self,
        base_url: Optional[str] = None,
        user: Optional[str] = None,
        api_token: Optional[str] = None,
        max_results: Optional[int] = None,
    ):
      
        self.base_url = (base_url or settings.jira_url).strip().rstrip("/")
        self.auth = ((user or settings.jira_user).strip(), (api_token or settings.jira_api_token).strip())
        self.max_results = max_results or settings.jira_max_results
        self.headers = {"Accept": "application/json"}

    async def fetch_all_issues(
        self, project_key: str, updated_after: Optional[str] = None
    ) -> AsyncGenerator[dict, None]:
        
        jql = self._build_jql(project_key, updated_after)
        max_results = self.max_results
        next_page_token: Optional[str] = None
        total_fetched = 0

        logger.info(
            f"[Jira] Début fetch | project={project_key} | "
            f"delta={updated_after or 'non (full sync)'}"
        )

        async with httpx.AsyncClient() as client:
            while True:
                data = await self._fetch_page(client, jql, max_results, next_page_token)
                issues = data.get("issues", [])

                for issue in issues:
                    yield issue
                    total_fetched += 1

                next_page_token = data.get("nextPageToken")
                if not issues or not next_page_token:
                    break

        logger.info(f"[Jira] Fetch terminé | project={project_key} | total={total_fetched}")

    async def test_connection(self) -> bool:
        """Vérifie que l'API Jira est joignable avec les credentials configurés."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/rest/api/3/myself",
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10,
                )
                resp.raise_for_status()
            logger.info(f"[Jira] Connexion OK | instance={self.base_url}")
            return True
        except Exception as e:
            logger.error(f"[Jira] Connexion échouée : {e}")
            return False

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        jql: str,
        max_results: int,
        next_page_token: Optional[str],
    ) -> dict:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,description,comment,status,"
                      "priority,assignee,reporter,created,updated,issuetype",
        }
        # Ne JAMAIS envoyer nextPageToken=None/null explicitement : l'API
        # rejette un token null sur la première requête ("invalid or expired").
        # On omet le paramètre tant qu'on n'a pas un vrai token du serveur.
        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/search/jql",
                params=params,
                auth=self.auth,
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Jira] Erreur API (status={e.response.status_code}) | "
                f"token={next_page_token or 'initial'} : {e}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[Jira] Erreur réseau | token={next_page_token or 'initial'} : {e}")
            raise

        return resp.json()

    @staticmethod
    def _build_jql(project_key: str, updated_after: Optional[str]) -> str:
        jql = f'project = "{project_key}"'
        if updated_after:
            jql += f' AND updated >= "{updated_after}"'
        jql += " ORDER BY updated ASC"
        return jql