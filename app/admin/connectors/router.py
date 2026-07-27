

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.connectors.models import (
    ConnectorCreate,
    ConnectorDetail,
    ConnectorSummary,
    ConnectorUpdate,
    ChatHistoryItem,
)
from app.admin.connectors.repository import DuplicateInstanceLabelError
from app.admin.connectors.service import ConnectorService
from app.api.router import _orchestrator
from app.db.database import get_db
from config import settings

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ScopedChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=6)


def get_service() -> ConnectorService:
    return ConnectorService()


@router.get("", response_model=list[ConnectorSummary])
async def list_connectors(
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    return await service.list_connectors(session)


@router.get("/{connector_id}", response_model=ConnectorDetail)
async def get_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    connector = await service.get_connector(session, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")
    return connector


@router.post("", response_model=ConnectorDetail, status_code=201)
async def create_connector(
    payload: ConnectorCreate,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    try:
        return await service.create_connector(session, payload)
    except DuplicateInstanceLabelError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/{connector_id}", response_model=ConnectorDetail)
async def update_connector(
    connector_id: UUID,
    payload: ConnectorUpdate,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    try:
        connector = await service.update_connector(session, connector_id, payload)
    except DuplicateInstanceLabelError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")
    return connector


@router.patch("/{connector_id}/toggle", response_model=ConnectorDetail)
async def toggle_connector(
    connector_id: UUID,
    enabled: bool,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    connector = await service.toggle_connector(session, connector_id, enabled)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")
    return connector


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    deleted = await service.delete_connector(session, connector_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")


@router.post("/{connector_id}/test-connection")
async def test_connection(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    connector = await service.get_connector(session, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")

    success = await service.test_connection(session, connector_id)
    return {"success": success}


@router.post("/{connector_id}/sync")
async def sync_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
    x_sync_secret: str = Header(default=""),
):
    # Contrôle optionnel : n'a d'effet QUE si un secret est configuré
    # côté serveur (settings.lambda_sync_secret). Vide en dev par
    # défaut — pas de friction pour les tests manuels de ce projet.
    if settings.lambda_sync_secret and x_sync_secret != settings.lambda_sync_secret:
        raise HTTPException(status_code=401, detail="Secret de synchronisation invalide")

    connector = await service.get_connector(session, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")

    try:
        result = await service.trigger_sync(session, connector_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return result


@router.post("/{connector_id}/test-chat")
async def test_chat(
    connector_id: UUID,
    payload: ScopedChatRequest,
    session: AsyncSession = Depends(get_db),
    service: ConnectorService = Depends(get_service),
):
    """
    Chat scopé à CETTE instance (panneau "Testez cette instance" de
    l'écran Connecteurs). Réutilise l'orchestrateur RAG existant tel
    quel — Rule/LLM Router tournent normalement pour l'extraction de
    filtres et le scope, mais la source ET l'instance précise sont
    forcées (voir Orchestrator.ask(forced_sources=..., forced_instance_id=...)).

    Isolation par instance précise, pas seulement par type de source —
    fonctionne pour les documents synchronisés APRÈS ce fix (tagués
    avec connector_instance_id dans leur metadata). Les documents
    synchronisés avant restent invisibles pour un chat scopé tant
    qu'une resynchronisation n'a pas eu lieu (cf CONTEXTE_PROJET.md).
    """
    connector = await service.get_connector(session, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connecteur introuvable")

    response = await _orchestrator.ask(
        question=payload.question,
        forced_sources=[connector.source_type],
        forced_instance_id=str(connector_id),
        conversation_history=[
            item.model_dump() for item in payload.history
        ],
    )

    return {
        "question": payload.question,
        "standalone_question": response.question,
        "answer": response.answer,
        "model": response.model,
        "sources": response.sources,
    }
