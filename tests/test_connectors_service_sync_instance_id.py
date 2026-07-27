

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.admin.connectors.crypto import encrypt_auth_fields
from app.admin.connectors.service import ConnectorService
from app.core.models import SyncResult
from config import settings


@pytest.fixture
def fake_repo():
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    repo.record_sync_result = AsyncMock()
    return repo


@pytest.fixture
def service(fake_repo):
    return ConnectorService(repository=fake_repo)


@pytest.fixture(autouse=True)
def no_lambda_arn(monkeypatch):
    monkeypatch.setattr(settings, "sync_lambda_arn", "")


@pytest.mark.asyncio
async def test_trigger_sync_passe_le_vrai_connector_id_au_pipeline(service, fake_repo):
    connector_id = uuid4()
    row = {
        "id": connector_id,
        "source_type": "jira",
        "auth_encrypted": encrypt_auth_fields({"url": "u", "email": "e", "token": "t"}),
        "sync_scope": {"projects": ["IH"]},
    }
    fake_repo.get_by_id.return_value = row

    fake_jira_connector = MagicMock()

    with patch(
        "app.admin.connectors.service.build_connectors_for_sync",
        return_value=[fake_jira_connector],
    ), patch(
        "app.admin.connectors.service.build_transformer",
        return_value=MagicMock(),
    ), patch(
        "app.ingestion.pipeline.IngestionPipeline"
    ) as mock_pipeline_cls:
        mock_pipeline_instance = MagicMock()
        mock_pipeline_instance.run = AsyncMock(
            return_value=SyncResult(
                source_type="jira", success=True,
                total_fetched=1, total_documents=1, total_chunks=1,
            )
        )
        mock_pipeline_cls.return_value = mock_pipeline_instance

        await service.trigger_sync(None, connector_id)

    mock_pipeline_cls.assert_called_once()
    call_kwargs = mock_pipeline_cls.call_args.kwargs
    assert call_kwargs["connector_instance_id"] == str(connector_id)