import logging
import time
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.jira.pipeline import JiraConnector
from app.connectors.jira.transformer import JiraTransformer
from app.connectors.sharepoint.pipeline import SharePointConnector
from app.connectors.sharepoint.transformer import SharePointTransformer
from app.connectors.confluence.pipeline import ConfluenceConnector
from app.connectors.confluence.transformer import ConfluenceTransformer
from app.db.database import get_db
from app.db.vector_store import VectorStore
from app.ingestion.embeddings.embedder import Embedder
from app.ingestion.pipeline import IngestionPipeline
from app.rag.orchestrator import Orchestrator
from app.nl2sql.factory import build_nl2sql_agent
from app.nl2sql.query_logger import QueryLogger

logger = logging.getLogger(__name__)
router = APIRouter()

# Instance unique réutilisée entre les requêtes — évite de recréer les
# composants (routers, reranker, generator) à chaque appel. Les modèles
# lourds (embedder, cross-encoder) restent chargés une seule fois en
# mémoire grâce au lazy loading déjà en place dans chaque module.
_orchestrator = Orchestrator()
_query_logger = QueryLogger()


class SyncRequest(BaseModel):
    project_key:   Optional[str] = None
    list_title:    Optional[str] = None
    space_key:     Optional[str] = None
    updated_after: Optional[str] = None


class SearchRequest(BaseModel):
    question: str
    user_id:  Optional[str] = None


def _build_jira_pipeline(request: SyncRequest) -> IngestionPipeline:
    return IngestionPipeline(
        connector   = JiraConnector(project_key=request.project_key),
        transformer = JiraTransformer(),
        embedder    = Embedder(),
        store       = VectorStore(),
    )


def _build_sharepoint_pipeline(request: SyncRequest) -> IngestionPipeline:
    return IngestionPipeline(
        connector   = SharePointConnector(list_title=request.list_title),
        transformer = SharePointTransformer(),
        embedder    = Embedder(),
        store       = VectorStore(),
    )


def _build_confluence_pipeline(request: SyncRequest) -> IngestionPipeline:
    return IngestionPipeline(
        connector   = ConfluenceConnector(space_key=request.space_key),
        transformer = ConfluenceTransformer(),
        embedder    = Embedder(),
        store       = VectorStore(),
    )


PIPELINE_FACTORIES = {
    "jira":        _build_jira_pipeline,
    "sharepoint":  _build_sharepoint_pipeline,
    "confluence":  _build_confluence_pipeline,
}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingestion/{source}/sync", summary="Synchroniser une source")
async def sync_source(source: str, request: SyncRequest) -> dict:
    factory = PIPELINE_FACTORIES.get(source)
    if factory is None:
        raise HTTPException(
            status_code = 404,
            detail      = f"Source inconnue : '{source}'. "
                          f"Disponibles : {list(PIPELINE_FACTORIES)}",
        )

    try:
        pipeline = factory(request)
        result   = await pipeline.run(since=request.updated_after)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error_message)

    return {
        "status":              "ok",
        "source":              source,
        "documents_processed": result.total_documents,
        "chunks_created":      result.total_chunks,
        "total_fetched":       result.total_fetched,
    }


@router.post("/search", summary="Recherche RAG (pipeline orchestrateur complet)")
async def search(request: SearchRequest) -> dict:
    t_start = time.time()

    try:
        response = await _orchestrator.ask(
            question = request.question,
            user_id  = request.user_id,
        )
        t_total = time.time() - t_start

        return {
            "question":              response.question,
            "answer":                response.answer,
            "model":                 response.model,
            "sources":               response.sources,
            "total_chunks_searched": response.total_chunks_searched,
            "performance": {
                "total_ms": round(t_total * 1000, 1),
            },
        }

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ==================================================================
# NL2SQL — administration et monitoring
# ==================================================================

@router.post("/nl2sql/rescan-schema", summary="Force un re-scan du schéma cible")
async def rescan_nl2sql_schema() -> dict:
    agent = build_nl2sql_agent()
    try:
        schema = await agent.rescan_schema()
        return {
            "status":          "ok",
            "connection_id":   schema.connection_id,
            "engine_dialect":  schema.engine_dialect,
            "tables_scanned":  len(schema.tables),
            "scanned_at":      schema.scanned_at,
        }
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/nl2sql/monitoring/stats", summary="Stats dashboard SQL Monitoring")
async def nl2sql_monitoring_stats(
    since_days: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _query_logger.get_stats(db, since_days=since_days)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/nl2sql/monitoring/queries", summary="Requêtes NL2SQL récentes")
async def nl2sql_monitoring_queries(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return {"queries": await _query_logger.get_recent(db, limit=limit)}
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc