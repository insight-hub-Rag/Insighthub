
from typing import Any


class UnknownSourceTypeError(Exception):
    pass


def build_client(source_type: str, auth_fields: dict[str, Any]):
    if source_type == "jira":
        from app.connectors.jira.client import JiraClient
        return JiraClient(
            base_url=auth_fields.get("url"),
            user=auth_fields.get("email"),
            api_token=auth_fields.get("token"),
        )

    if source_type == "confluence":
        from app.connectors.confluence.client import ConfluenceClient
        return ConfluenceClient(
            url=auth_fields.get("url"),
            user=auth_fields.get("email"),
            api_token=auth_fields.get("token"),
        )

    if source_type == "sharepoint":
        from app.connectors.sharepoint.client import SharePointClient
        return SharePointClient(
            site_url=auth_fields.get("site_url"),
            client_id=auth_fields.get("client_id"),
            client_secret=auth_fields.get("client_secret"),
        )

    if source_type == "servicenow":
        from app.connectors.servicenow.client import ServiceNowClient
        return ServiceNowClient(
            instance_url=auth_fields.get("instance_url"),
            username=auth_fields.get("username"),
            password=auth_fields.get("password"),
        )

    raise UnknownSourceTypeError(f"Source type inconnu : {source_type!r}")