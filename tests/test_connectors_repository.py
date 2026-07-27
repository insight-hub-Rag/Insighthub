

import pytest
import pytest_asyncio

from app.db.database import AsyncSessionLocal
from app.admin.connectors.repository import ConnectorRepository


@pytest_asyncio.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s


@pytest_asyncio.fixture
async def repo():
    return ConnectorRepository()


@pytest.mark.asyncio
async def test_create_and_get_by_id(session, repo):
    created = await repo.create(
        session,
        source_type="jira",
        instance_label="Jira — Test Repository",
        auth_encrypted="fake-encrypted-blob",
        sync_scope={"projects": ["TEST"]},
        sync_frequency_minutes=15,
    )
    assert created["source_type"] == "jira"
    assert created["instance_label"] == "Jira — Test Repository"
    assert created["is_enabled"] is True

    fetched = await repo.get_by_id(session, created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]

    # Nettoyage — ne pas laisser de données de test en base
    await repo.delete(session, created["id"])


@pytest.mark.asyncio
async def test_update_partial_fields(session, repo):
    created = await repo.create(
        session,
        source_type="jira",
        instance_label="Jira — Test Update",
        auth_encrypted="fake-encrypted-blob",
        sync_scope={},
        sync_frequency_minutes=15,
    )

    updated = await repo.update(
        session, created["id"], {"sync_frequency_minutes": 60}
    )
    assert updated["sync_frequency_minutes"] == 60
    # Les autres champs ne doivent pas avoir bougé
    assert updated["instance_label"] == "Jira — Test Update"

    await repo.delete(session, created["id"])


@pytest.mark.asyncio
async def test_record_sync_result(session, repo):
    created = await repo.create(
        session,
        source_type="jira",
        instance_label="Jira — Test Sync",
        auth_encrypted="fake-encrypted-blob",
        sync_scope={},
        sync_frequency_minutes=15,
    )

    await repo.record_sync_result(
        session,
        created["id"],
        success=True,
        stats={"total_fetched": 42, "modified": 3, "duration_seconds": 1.2},
    )

    fetched = await repo.get_by_id(session, created["id"])
    assert fetched["last_sync_status"] == "success"
    assert fetched["last_sync_at"] is not None
    assert fetched["last_sync_stats"]["total_fetched"] == 42

    await repo.delete(session, created["id"])


@pytest.mark.asyncio
async def test_delete_returns_false_if_not_found(session, repo):
    import uuid
    deleted = await repo.delete(session, uuid.uuid4())
    assert deleted is False


@pytest.mark.asyncio
async def test_list_all_includes_created_connector(session, repo):
    created = await repo.create(
        session,
        source_type="confluence",
        instance_label="Confluence — Test List",
        auth_encrypted="fake-encrypted-blob",
        sync_scope={},
        sync_frequency_minutes=30,
    )

    all_connectors = await repo.list_all(session)
    ids = [c["id"] for c in all_connectors]
    assert created["id"] in ids

    await repo.delete(session, created["id"])