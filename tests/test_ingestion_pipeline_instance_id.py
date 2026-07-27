

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import Chunk, RawRecord
from app.ingestion.pipeline import IngestionPipeline


def _make_mocks():
    record = RawRecord(source_type="jira", record_id="IH-1", raw_data={})

    async def fake_fetch(since=None):
        yield record

    connector = MagicMock()
    connector.source_type = "jira"
    connector.test_connection = AsyncMock(return_value=True)
    connector.fetch = fake_fetch

    chunk = Chunk(
        chunk_id="jira-IH-1-0", document_id="IH-1", source_type="jira",
        content="contenu", metadata={"status": "En cours"},
    )
    transformer = MagicMock()
    transformer.transform.return_value = [chunk]

    embedder = MagicMock()
    embedder.embed_chunks = MagicMock()

    store = MagicMock()
    store.upsert_document_with_chunks = AsyncMock(return_value=1)

    return connector, transformer, embedder, store, chunk


@pytest.mark.asyncio
async def test_avec_connector_instance_id_tague_le_metadata():
    connector, transformer, embedder, store, chunk = _make_mocks()

    pipeline = IngestionPipeline(
        connector, transformer, embedder, store,
        connector_instance_id="abc-123",
    )
    result = await pipeline.run()

    assert result.success is True
    assert chunk.metadata["connector_instance_id"] == "abc-123"
    # Le reste du metadata existant (status) ne doit pas être perdu
    assert chunk.metadata["status"] == "En cours"


@pytest.mark.asyncio
async def test_sans_connector_instance_id_ne_touche_pas_au_metadata():
    """Non-régression : sans le paramètre (tous les appels existants
    avant ce fix), le comportement doit être strictement identique."""
    connector, transformer, embedder, store, chunk = _make_mocks()

    pipeline = IngestionPipeline(connector, transformer, embedder, store)
    result = await pipeline.run()

    assert result.success is True
    assert "connector_instance_id" not in chunk.metadata