from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.connectors.jira.pipeline import JiraConnector
from app.connectors.jira.transformer import JiraTransformer
from app.connectors.sharepoint.pipeline import SharePointConnector
from app.connectors.sharepoint.transformer import SharePointTransformer
from app.db.vector_store import VectorStore
from app.ingestion.embeddings.embedder import Embedder
from app.ingestion.pipeline import IngestionPipeline

router = APIRouter()


class SyncRequest(BaseModel):
    project_key: Optional[str] = None
    list_title: Optional[str] = None
    updated_after: Optional[str] = None


# Registre des sources disponibles : source_type -> factory de pipeline.
# Ajouter une source = ajouter une entrée ici, rien d'autre à changer
# dans ce fichier (Open/Closed Principle).
def _build_jira_pipeline(request: SyncRequest) -> IngestionPipeline:
    connector = JiraConnector(project_key=request.project_key)
    return IngestionPipeline(
        connector=connector,
        transformer=JiraTransformer(),
        embedder=Embedder(),
        store=VectorStore(),
    )


def _build_sharepoint_pipeline(request: SyncRequest) -> IngestionPipeline:
    connector = SharePointConnector(list_title=request.list_title)
    return IngestionPipeline(
        connector=connector,
        transformer=SharePointTransformer(),
        embedder=Embedder(),
        store=VectorStore(),
    )


PIPELINE_FACTORIES = {
    "jira": _build_jira_pipeline,
    "sharepoint": _build_sharepoint_pipeline,
}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingestion/{source}/sync")
async def sync_source(source: str, request: SyncRequest) -> dict:
    factory = PIPELINE_FACTORIES.get(source)
    if factory is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source inconnue : '{source}'. Sources disponibles : {list(PIPELINE_FACTORIES)}",
        )

    try:
        pipeline = factory(request)
        result = await pipeline.run(since=request.updated_after)
    except ValueError as exc:
        # ex: aucun project_key configuré pour Jira
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error_message)

    return {
        "status": "ok",
        "source": source,
        "documents_processed": result.total_documents,
        "chunks_created": result.total_chunks,
        "total_fetched": result.total_fetched,
    }