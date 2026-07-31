import logging
import time
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
import uuid
from pathlib import Path
from sqlalchemy import create_engine
from config import settings
from app.nl2sql import factory
from app.nl2sql.schema_scanner import SchemaScanner
from app.nl2sql.connection import target_connection_manager
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

def update_env_variable(key: str, value: str):
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines), encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")


@router.post("/nl2sql/upload-dump", summary="Upload et matérialisation d'un dump SQL (Multi-moteur: Postgres, MySQL, Oracle, SQL Server, SQLite)")
async def upload_sql_dump(
    file: UploadFile = File(...),
    engine_type: str = Form("sqlite"),
    tenant_id: str = Form("default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.admin.connectors.service import ConnectorService

    ALLOWED_EXTENSIONS = {".sql", ".sqlite", ".sqlite3", ".db", ".db3", ".s3db", ".sl3", ".txt", ".dump"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed_str = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Extension de fichier non autorisée. Extensions autorisées : ({allowed_str})"
        )

    MAX_FILE_SIZE = 50 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Le fichier est trop volumineux (max 50 Mo).")

    service = ConnectorService()
    try:
        res = await service.process_dump_upload(
            session=db,
            file_name=file.filename or "dump.sql",
            file_bytes=contents,
            engine_type=engine_type,
            tenant_id=tenant_id,
        )
        return res.model_dump()
    except Exception as exc:
        logger.error(f"Failed to process dump upload: {exc}")
        raise HTTPException(status_code=400, detail=f"Erreur lors du traitement du dump : {str(exc)}")


@router.post("/nl2sql/upload-sqlite", summary="Charge un fichier SQLite de façon sécurisée et l'analyse")
async def upload_sqlite_database(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    CORRECTIF : cet endpoint dupliquait toute la logique de
    process_dump_upload avec connection_id="default" codé en dur,
    contournant totalement l'isolation par connecteur mise en place
    (une base = un connector_id unique, une seule active à la fois).
    Il délègue désormais à ConnectorService.process_dump_upload(),
    exactement comme /nl2sql/upload-dump — plus de deuxième chemin
    divergent.
    """
    from app.admin.connectors.service import ConnectorService

    ALLOWED_SQLITE_EXTENSIONS = {".sqlite", ".sqlite3", ".db", ".db3", ".s3db", ".sl3", ".sql"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_SQLITE_EXTENSIONS:
        allowed_str = ", ".join(sorted(ALLOWED_SQLITE_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Extension de fichier non autorisée. Seuls les fichiers ({allowed_str}) sont autorisés."
        )

    MAX_FILE_SIZE = 20 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Le fichier est trop volumineux (max 20 Mo).")

    service = ConnectorService()
    try:
        res = await service.process_dump_upload(
            session=db,
            file_name=file.filename or "database.sqlite",
            file_bytes=contents,
            engine_type="sqlite",
        )
        return res.model_dump()
    except Exception as exc:
        logger.error(f"Failed to process sqlite upload: {exc}")
        raise HTTPException(status_code=400, detail=f"Erreur lors du traitement du fichier : {str(exc)}")


@router.post("/nl2sql/rescan-schema", summary="Ré-analyser le schéma (nécessite un nouvel upload)")
async def rescan_nl2sql_schema() -> dict:
    """
    CORRECTIF : NL2SQLAgent.rescan_schema() n'existe plus — il n'y a
    plus de connexion persistante à "rescanner" à ce stade du projet
    (sandbox détruit après le scan initial, dump schema-only sans
    exécution réelle). Pour changer/rafraîchir un schéma, il faut
    ré-uploader le dump via /nl2sql/upload-dump, qui recrée un
    connecteur et un schéma à jour.
    """
    raise HTTPException(
        status_code=400,
        detail=(
            "Le rescan à chaud n'est pas disponible à ce stade : "
            "aucune connexion persistante n'est conservée après l'upload initial. "
            "Ré-uploadez le dump via /nl2sql/upload-dump pour rafraîchir le schéma."
        ),
    )


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