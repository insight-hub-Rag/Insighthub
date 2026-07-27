

from typing import Any

from app.connectors.jira.pipeline import JiraConnector
from app.connectors.jira.transformer import JiraTransformer
from app.connectors.confluence.pipeline import ConfluenceConnector
from app.connectors.confluence.transformer import ConfluenceTransformer
from app.connectors.sharepoint.pipeline import SharePointConnector
from app.connectors.sharepoint.transformer import SharePointTransformer


class SyncNotSupportedError(Exception):
   


def build_connectors_for_sync(source_type: str, client: Any, sync_scope: dict) -> list:
    if source_type == "jira":
        projects = sync_scope.get("projects") or []
        if not projects:
            raise SyncNotSupportedError(
                "sync_scope ne contient aucun 'projects' pour cette instance Jira. "
                "Renseigne au moins une clé de projet dans le périmètre de "
                "synchronisation avant de lancer une sync."
            )
        return [JiraConnector(client=client, project_key=p) for p in projects]

    if source_type == "confluence":
        spaces = sync_scope.get("spaces") or []
        if not spaces:
            raise SyncNotSupportedError(
                "sync_scope ne contient aucun 'spaces' pour cette instance Confluence."
            )
        return [ConfluenceConnector(client=client, space_key=s) for s in spaces]

    if source_type == "sharepoint":
        lists = sync_scope.get("lists") or []
        if not lists:
            raise SyncNotSupportedError(
                "sync_scope ne contient aucun 'lists' pour cette instance SharePoint."
            )
        return [SharePointConnector(client=client, list_title=l) for l in lists]

    if source_type == "servicenow":
        raise SyncNotSupportedError(
            "La synchronisation ServiceNow n'est pas encore branchée : le "
            "transformer et le connecteur (app/connectors/servicenow/) "
            "restent à écrire. Seul 'test-connection' fonctionne pour "
            "l'instant sur cette source."
        )

    raise SyncNotSupportedError(f"Source type inconnu : {source_type!r}")


def build_transformer(source_type: str):
    if source_type == "jira":
        return JiraTransformer()
    if source_type == "confluence":
        return ConfluenceTransformer()
    if source_type == "sharepoint":
        return SharePointTransformer()
    raise SyncNotSupportedError(f"Aucun transformer disponible pour : {source_type!r}")