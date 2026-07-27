

from loguru import logger

from app.core.base_connector import BaseConnector
from app.core.base_transformer import BaseTransformer
from app.core.models import SyncResult
from app.db.vector_store import VectorStore
from app.ingestion.embeddings.embedder import Embedder


class IngestionPipeline:

    def __init__(
        self,
        connector: BaseConnector,
        transformer: BaseTransformer,
        embedder: Embedder,
        store: VectorStore,
        connector_instance_id: str | None = None,
    ):
      
        self._connector = connector
        self._transformer = transformer
        self._embedder = embedder
        self._store = store
        self._connector_instance_id = connector_instance_id

    async def run(self, since: str | None = None) -> SyncResult:
        """
        Exécute le pipeline complet pour la source du connecteur injecté.

        Args:
            since: curseur optionnel pour une synchronisation incrémentale.
                   Si None, récupère tout (full sync).
        """
        source = self._connector.source_type
        logger.info(f"[Pipeline] Démarrage | source={source}")

        if not await self._connector.test_connection():
            logger.error(f"[Pipeline] Connexion impossible | source={source}")
            return SyncResult(
                source_type=source,
                success=False,
                error_message="Connexion à la source impossible.",
            )

        result = SyncResult(source_type=source)

        try:
            async for record in self._connector.fetch(since=since):
                result.total_fetched += 1

                chunks = self._transformer.transform(record)
                if not chunks:
                    continue

                if self._connector_instance_id:
                    for chunk in chunks:
                        chunk.metadata["connector_instance_id"] = self._connector_instance_id

                self._embedder.embed_chunks(chunks)
                await self._store.upsert_document_with_chunks(
                    source_type=source,
                    document_id=record.record_id,
                    chunks=chunks,
                )

                result.total_documents += 1
                result.total_chunks += len(chunks)

            result.success = True

        except Exception as e:
            logger.error(f"[Pipeline] Erreur | source={source} : {e}")
            result.success = False
            result.error_message = str(e)

        logger.info(
            f"[Pipeline] {'OK' if result.success else 'ERREUR'} | source={source} | "
            f"fetched={result.total_fetched} | documents={result.total_documents} | "
            f"chunks={result.total_chunks}"
        )
        return result