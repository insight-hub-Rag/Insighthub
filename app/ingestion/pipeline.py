"""
IngestionPipeline : orchestre le flux complet d'ingestion pour N'IMPORTE
QUELLE source, à condition qu'elle respecte BaseConnector / BaseTransformer.

connector.fetch() -> transformer.transform() -> embedder.embed_chunks() -> store.upsert()

Le pipeline ne connaît JAMAIS Jira, ServiceNow ou SharePoint directement —
seulement les interfaces. Ajouter une nouvelle source ne nécessite donc
aucune modification de cette classe (Open/Closed Principle). C'est la
pièce qui matérialise le Strategy Pattern demandé pour ce sprint.

Tout est injecté par constructeur (Dependency Injection) : connector,
transformer, embedder et store sont des dépendances passées de l'extérieur,
jamais instanciées en dur ici — ce qui rend le pipeline testable avec des
faux objets (mocks) sans toucher au réseau, à un modèle d'embedding ou à
une vraie base de données.
"""

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
    ):
        self._connector = connector
        self._transformer = transformer
        self._embedder = embedder
        self._store = store

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
