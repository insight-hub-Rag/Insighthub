

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.admin.connectors.crypto import encrypt_auth_fields
from app.admin.connectors.models import ConnectorCreate, ConnectorUpdate
from app.admin.connectors.service import ConnectorService
from config import settings


def _fake_row(**overrides):
    base = {
        "id": uuid4(),
        "source_type": "jira",
        "instance_label": "Jira — Test",
        "is_enabled": True,
        "auth_encrypted": encrypt_auth_fields({"url": "u", "email": "e", "token": "t"}),
        "sync_scope": {"projects": ["IH"]},
        "sync_frequency_minutes": 15,
        "last_sync_at": None,
        "last_sync_status": None,
        "last_sync_stats": None,
        "last_error": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def fake_repo():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def service(fake_repo):
    return ConnectorService(repository=fake_repo)


@pytest.fixture(autouse=True)
def with_lambda_arn(monkeypatch):
    """Par défaut dans ces tests, AWS est 'configuré' (ARN présent) —
    les tests spécifiques au cas 'non configuré' l'écrasent eux-mêmes."""
    monkeypatch.setattr(settings, "sync_lambda_arn", "arn:aws:lambda:us-east-1:123:function:sync_trigger")


@pytest.mark.asyncio
async def test_create_connector_appelle_eventbridge(service, fake_repo):
    row = _fake_row()
    fake_repo.create.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule") as mock_rule:
        await service.create_connector(None, ConnectorCreate(
            source_type="jira", instance_label="Jira — Test",
            auth_fields={"url": "u", "email": "e", "token": "t"},
            sync_scope={"projects": ["IH"]}, sync_frequency_minutes=15,
        ))

    mock_rule.assert_called_once_with(
        connector_id=str(row["id"]), frequency_minutes=15,
        lambda_arn=settings.sync_lambda_arn, enabled=True,
    )


@pytest.mark.asyncio
async def test_update_frequence_appelle_eventbridge(service, fake_repo):
    row = _fake_row(sync_frequency_minutes=60)
    fake_repo.update.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule") as mock_rule:
        await service.update_connector(
            None, row["id"], ConnectorUpdate(sync_frequency_minutes=60)
        )

    mock_rule.assert_called_once()


@pytest.mark.asyncio
async def test_update_sans_changer_frequence_n_appelle_pas_eventbridge(service, fake_repo):
    row = _fake_row()
    fake_repo.update.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule") as mock_rule:
        await service.update_connector(
            None, row["id"], ConnectorUpdate(instance_label="Nouveau nom")
        )

    mock_rule.assert_not_called()


@pytest.mark.asyncio
async def test_toggle_appelle_eventbridge(service, fake_repo):
    row = _fake_row(is_enabled=False)
    fake_repo.update.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule") as mock_rule:
        await service.toggle_connector(None, row["id"], enabled=False)

    mock_rule.assert_called_once()
    assert mock_rule.call_args.kwargs["enabled"] is False


@pytest.mark.asyncio
async def test_delete_appelle_delete_rule(service, fake_repo):
    connector_id = uuid4()

    with patch("infrastructure.eventbridge.rules.delete_rule") as mock_delete:
        await service.delete_connector(None, connector_id)

    mock_delete.assert_called_once_with(str(connector_id))


@pytest.mark.asyncio
async def test_erreur_aws_ne_casse_pas_le_create(service, fake_repo):
    """Best-effort : si EventBridge plante, create_connector doit quand
    même réussir et retourner le connecteur créé."""
    row = _fake_row()
    fake_repo.create.return_value = row

    with patch(
        "infrastructure.eventbridge.rules.create_or_update_rule",
        side_effect=Exception("AWS indisponible"),
    ):
        result = await service.create_connector(None, ConnectorCreate(
            source_type="jira", instance_label="Jira — Test",
            auth_fields={"url": "u", "email": "e", "token": "t"},
            sync_scope={"projects": ["IH"]}, sync_frequency_minutes=15,
        ))

    assert result.id == row["id"]  # le CRUD a bien réussi malgré l'échec AWS


@pytest.mark.asyncio
async def test_update_serialise_sync_scope_en_json(service, fake_repo):
    """Régression : sync_scope doit être une chaîne JSON quand il arrive
    au repository (colonne jsonb), jamais un dict Python brut — sinon
    asyncpg plante avec 'dict object has no attribute encode'."""
    row = _fake_row()
    fake_repo.update.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule"):
        await service.update_connector(
            None, row["id"],
            ConnectorUpdate(sync_scope={"spaces": ["insighthub"]}),
        )

    passed_fields = fake_repo.update.call_args.args[2]
    assert isinstance(passed_fields["sync_scope"], str)
    assert json.loads(passed_fields["sync_scope"]) == {"spaces": ["insighthub"]}


@pytest.mark.asyncio
async def test_sans_lambda_arn_configure_rien_n_est_appele(service, fake_repo, monkeypatch):
    """Si settings.sync_lambda_arn est vide (dev sans AWS réel), aucun
    appel EventBridge ne doit être tenté."""
    monkeypatch.setattr(settings, "sync_lambda_arn", "")
    row = _fake_row()
    fake_repo.create.return_value = row

    with patch("infrastructure.eventbridge.rules.create_or_update_rule") as mock_rule:
        await service.create_connector(None, ConnectorCreate(
            source_type="jira", instance_label="Jira — Test",
            auth_fields={"url": "u", "email": "e", "token": "t"},
            sync_scope={"projects": ["IH"]}, sync_frequency_minutes=15,
        ))

    mock_rule.assert_not_called()