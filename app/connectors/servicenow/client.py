from typing import AsyncGenerator, Optional

import httpx
from loguru import logger
from config import settings

# Champs récupérés par défaut pour une table de type "incident".
DEFAULT_FIELDS = (
    "number,short_description,description,state,priority,category,"
    "assigned_to,opened_by,sys_created_on,sys_updated_on,comments,work_notes"
)


class ServiceNowClient:
    """
    Client HTTP bas niveau pour la Table API REST de ServiceNow
    (/api/now/table/{table}). Ne fait aucune transformation.
    Authentification Basic Auth (username/password).
    """

    def __init__(self):
        self.base_url = settings.servicenow_instance_url.rstrip("/")
        self.auth = (settings.servicenow_username, settings.servicenow_password)
        self.headers = {"Accept": "application/json"}

    async def fetch_all_records(
        self, table: str, updated_after: Optional[str] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Génère les enregistrements d'une table, page par page.
        Pagination par offset (sysparm_offset / sysparm_limit).
        """
        query = self._build_query(updated_after)
        page_size = settings.servicenow_page_size
        offset = 0
        total_fetched = 0

        logger.info(
            f"[ServiceNow] Début fetch | table={table} | "
            f"delta={updated_after or 'non (full sync)'}"
        )

        async with httpx.AsyncClient() as client:
            while True:
                records = await self._fetch_page(client, table, query, page_size, offset)

                for record in records:
                    yield record
                    total_fetched += 1

                if len(records) < page_size:
                    break
                offset += page_size

        logger.info(f"[ServiceNow] Fetch terminé | table={table} | total={total_fetched}")

    async def test_connection(self) -> bool:
        """Vérifie que l'API ServiceNow est joignable avec les credentials configurés."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/api/now/table/sys_user",
                    params={"sysparm_limit": 1},
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10,
                )
                resp.raise_for_status()
            logger.info(f"[ServiceNow] Connexion OK | instance={self.base_url}")
            return True
        except Exception as e:
            logger.error(f"[ServiceNow] Connexion échouée : {e}")
            return False

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        table: str,
        query: str,
        page_size: int,
        offset: int,
    ) -> list[dict]:
        params = {
            "sysparm_query": query,
            "sysparm_limit": page_size,
            "sysparm_offset": offset,
            "sysparm_fields": DEFAULT_FIELDS,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
        }

        try:
            resp = await client.get(
                f"{self.base_url}/api/now/table/{table}",
                params=params,
                auth=self.auth,
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[ServiceNow] Erreur API (status={e.response.status_code}) | "
                f"table={table} | offset={offset} : {e}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[ServiceNow] Erreur réseau | table={table} | offset={offset} : {e}")
            raise

        return resp.json().get("result", [])

    @staticmethod
    def _build_query(updated_after: Optional[str]) -> str:
        if updated_after:
            return f"sys_updated_on>={updated_after}^ORDERBYsys_updated_on"
        return "ORDERBYsys_updated_on"