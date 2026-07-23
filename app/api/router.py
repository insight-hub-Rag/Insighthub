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
from app.connectors.servicenow.pipeline import ServiceNowConnector
from app.connectors.servicenow.transformer import ServiceNowTransformer
from app.db.database import get_db
from app.db.vector_store import VectorStore
from app.db import chat_history as chat_history_repo
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
    table_name:    Optional[str] = None
    updated_after: Optional[str] = None


class SearchRequest(BaseModel):
    question: str
    user_id:  Optional[str] = None


class ChatConversationCreate(BaseModel):
    id:          str
    title:       str
    source:      str = ""
    latency_ms:  int = 0
    group_label: str = "Aujourd'hui"


class ChatConversationPatch(BaseModel):
    title:    Optional[str]  = None
    favorite: Optional[bool] = None
    trashed:  Optional[bool] = None


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


def _build_servicenow_pipeline(request: SyncRequest) -> IngestionPipeline:
    return IngestionPipeline(
        connector   = ServiceNowConnector(),
        transformer = ServiceNowTransformer(),
        embedder    = Embedder(),
        store       = VectorStore(),
    )


PIPELINE_FACTORIES = {
    "jira":        _build_jira_pipeline,
    "sharepoint":  _build_sharepoint_pipeline,
    "confluence":  _build_confluence_pipeline,
    "servicenow":  _build_servicenow_pipeline,
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


# ==================================================================
# Chat history — persistance des conversations
# ==================================================================

@router.get("/chat/history", summary="Récupérer l'historique des conversations")
async def get_chat_history(
    limit: int = 100,
    include_trashed: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        conversations = await chat_history_repo.get_conversations(
            db, limit=limit, include_trashed=include_trashed
        )
        return {"conversations": conversations}
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/history", summary="Créer ou mettre à jour une conversation")
async def save_chat_conversation(
    request: ChatConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        saved = await chat_history_repo.save_conversation(db, request.model_dump())
        return saved
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/chat/history/{conv_id}", summary="Mettre à jour une conversation (titre, favori, corbeille)")
async def update_chat_conversation(
    conv_id: str,
    request: ChatConversationPatch,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        patch = {k: v for k, v in request.model_dump().items() if v is not None}
        updated = await chat_history_repo.update_conversation(db, conv_id, patch)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{conv_id}' introuvable")
        return updated
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/chat/history/{conv_id}", summary="Supprimer définitivement une conversation")
async def delete_chat_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        deleted = await chat_history_repo.delete_conversation(db, conv_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Conversation '{conv_id}' introuvable")
        return {"status": "deleted", "id": conv_id}
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Chat messages (échanges Q/R) ──────────────────────────────────────────────

class ChatMessageCreate(BaseModel):
    id:              str
    conversation_id: str
    role:            str          # "user" | "assistant"
    content:         str
    sources:         list  = []
    latency_ms:      int   = 0


@router.get("/chat/history/{conv_id}/messages", summary="Messages d'une conversation")
async def get_conversation_messages(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        messages = await chat_history_repo.get_messages(db, conv_id)
        return {"messages": messages}
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/history/{conv_id}/messages", summary="Sauvegarder un message")
async def save_conversation_message(
    conv_id: str,
    request: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        if request.conversation_id != conv_id:
            raise HTTPException(status_code=400, detail="conv_id mismatch")
        saved = await chat_history_repo.save_message(db, request.model_dump())
        return saved
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

