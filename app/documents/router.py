"""
Documents Clients — Router FastAPI.

Endpoints :
  POST   /documents/upload          → Upload + extraction + indexation
  GET    /documents                 → Liste tous les documents du tenant
  GET    /documents/{id}            → Détail d'un document
  DELETE /documents/{id}            → Suppression (métadonnées + chunks)
  POST   /documents/{id}/reindex    → Relance l'indexation d'un document FAILED

Architecture :
  1. Réception du fichier multipart
  2. Stockage S3 (optionnel — si AWS_ACCESS_KEY_ID configuré, sinon skip)
  3. Sauvegarde des métadonnées en base (status=UPLOADED)
  4. Extraction texte (PDF/DOCX/TXT/CSV/PPTX)
  5. Nettoyage + Chunking
  6. Embedding + stockage pgvector (schema 'documents')
  7. Mise à jour statut → INDEXED (ou FAILED)

Le tout se passe en arrière-plan (BackgroundTask) pour ne pas bloquer la
réponse HTTP : le client reçoit immédiatement l'ID du document, puis peut
poller GET /documents/{id} pour suivre le statut.
"""

import logging
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _HAS_BOTO3 = True
except ImportError:
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception
    _HAS_BOTO3 = False
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from app.db.database import get_db
from app.db.vector_store import VectorStore, SCHEMA_BY_SOURCE
from app.documents.chunker import chunk_document
from app.documents.extractor import extract_and_clean
from app.documents.models import DocumentOut, DocumentStatus, DocumentUploadResponse
from app.documents.repository import DocumentRepository
from app.ingestion.embeddings.embedder import Embedder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents Clients"])

# Types de fichiers autorisés
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".csv", ".pptx", ".ppt"}
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

_repo = DocumentRepository()
_embedder = Embedder()
_store = VectorStore()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_extension(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _upload_to_s3(content: bytes, s3_key: str) -> Optional[str]:
    """Upload vers S3 si configuré. Retourne le s3_key ou None en cas d'échec/non configuré."""
    if not _HAS_BOTO3 or not settings.aws_access_key_id or not getattr(settings, "s3_bucket_name", ""):
        logger.info("[Documents] S3 non configuré — stockage local uniquement")
        return None
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        bucket = getattr(settings, "s3_bucket_name", "")
        s3.put_object(Bucket=bucket, Key=s3_key, Body=content)
        logger.info(f"[Documents] S3 upload OK : s3://{bucket}/{s3_key}")
        return s3_key
    except (BotoCoreError, ClientError) as e:
        logger.error(f"[Documents] S3 upload échoué : {e}")
        return None


# ── Tâche de fond : extraction → chunking → embedding → indexation ────────────

async def _process_document(
    doc_id: str,
    filename: str,
    content: bytes,
    tenant_id: str,
    user_id: Optional[str],
    s3_key: Optional[str],
) -> None:
    """Pipeline complet d'ingestion d'un document client (exécuté en arrière-plan)."""
    from app.db.database import AsyncSessionLocal
    if AsyncSessionLocal is None:
        logger.error("[Documents] Pas de session DB — indexation impossible")
        return

    async with AsyncSessionLocal() as session:
        try:
            # Statut intermédiaire
            await _repo.update_status(session, doc_id, DocumentStatus.PROCESSING)

            # 1. Extraction du texte
            text = extract_and_clean(filename, content)
            if not text:
                await _repo.update_status(
                    session, doc_id, DocumentStatus.FAILED,
                    error="Extraction de texte vide — format non supporté ou fichier corrompu."
                )
                return

            # 2. Chunking
            chunks = chunk_document(
                doc_id=doc_id,
                filename=filename,
                text=text,
                tenant_id=tenant_id,
                user_id=user_id,
                s3_key=s3_key,
            )
            if not chunks:
                await _repo.update_status(
                    session, doc_id, DocumentStatus.FAILED,
                    error="Aucun chunk généré après découpage."
                )
                return

            # 3. Embedding
            _embedder.embed_chunks(chunks)

            # 4. Stockage pgvector (schéma 'documents')
            await _store.upsert_document_with_chunks(
                source_type="documents",
                document_id=doc_id,
                chunks=chunks,
            )

            # 5. Mise à jour statut final
            await _repo.update_status(
                session, doc_id, DocumentStatus.INDEXED, chunk_count=len(chunks)
            )
            logger.info(f"[Documents] Document {doc_id} indexé avec {len(chunks)} chunks")

        except Exception as e:
            logger.exception(f"[Documents] Erreur d'indexation pour {doc_id}")
            await _repo.update_status(
                session, doc_id, DocumentStatus.FAILED,
                error=str(e)[:500]
            )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentUploadResponse, status_code=202,
             summary="Uploader un document client (PDF, DOCX, TXT, CSV, PPTX)")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tenant_id: str = Form(default="default"),
    user_id: Optional[str] = Form(default=None),
    session: AsyncSession = Depends(get_db),
):
    # Validation extension
    ext = _get_extension(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Format non supporté : {ext!r}. Formats acceptés : {sorted(ALLOWED_EXTENSIONS)}"
        )

    # Lecture + validation taille
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux ({len(content) // 1024 // 1024} Mo). Maximum : {MAX_FILE_SIZE_MB} Mo."
        )

    filename = file.filename or "document_sans_nom"

    # Upload S3 (optionnel)
    import uuid as _uuid
    doc_uuid = str(_uuid.uuid4())
    s3_key = f"documents/{tenant_id}/{doc_uuid}/{filename}"
    stored_s3_key = _upload_to_s3(content, s3_key)

    # Sauvegarde métadonnées en base
    doc = await _repo.create(
        session=session,
        filename=filename,
        file_type=ext.lstrip("."),
        file_size=len(content),
        tenant_id=tenant_id,
        user_id=user_id,
        s3_key=stored_s3_key,
    )
    # On force l'ID généré par create() en réutilisant le UUID créé
    # (le repo génère son propre UUID — on l'utilise directement)
    doc_id = doc.id

    # Lancement de l'indexation en arrière-plan
    background_tasks.add_task(
        _process_document,
        doc_id=doc_id,
        filename=filename,
        content=content,
        tenant_id=tenant_id,
        user_id=user_id,
        s3_key=stored_s3_key,
    )

    return DocumentUploadResponse(
        document_id=doc_id,
        filename=filename,
        status=DocumentStatus.UPLOADED,
        message="Document reçu. Extraction et indexation en cours...",
    )


@router.get("", response_model=list[DocumentOut],
            summary="Lister tous les documents clients")
async def list_documents(
    tenant_id: str = "default",
    user_id: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
):
    return await _repo.list_all(session, tenant_id=tenant_id, user_id=user_id)


@router.get("/{doc_id}", response_model=DocumentOut,
            summary="Détail d'un document client")
async def get_document(doc_id: str, session: AsyncSession = Depends(get_db)):
    doc = await _repo.get_by_id(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


@router.get("/{doc_id}/content", summary="Récupérer le contenu texte extrait et les chunks d'un document")
async def get_document_content(doc_id: str, session: AsyncSession = Depends(get_db)):
    doc = await _repo.get_by_id(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")

    from sqlalchemy import text
    result = await session.execute(
        text("""
            SELECT e.chunk_id, e.content, e.metadata
            FROM documents.embeddings e
            JOIN documents.documents d ON d.id = e.document_id
            WHERE d.external_id = :doc_id
            ORDER BY e.chunk_id
        """),
        {"doc_id": doc_id}
    )
    rows = result.mappings().all()

    chunks = [
        {
            "chunk_id": row["chunk_id"],
            "content": row["content"],
            "metadata": row["metadata"] or {},
        }
        for row in rows
    ]

    full_text = "\n\n".join(c["content"] for c in chunks)

    return {
        "document_id": doc_id,
        "filename": doc.filename,
        "status": doc.status,
        "chunk_count": len(chunks),
        "full_text": full_text,
        "chunks": chunks,
    }


@router.delete("/{doc_id}", status_code=204,
               summary="Supprimer un document client et ses chunks")
async def delete_document(doc_id: str, session: AsyncSession = Depends(get_db)):
    doc = await _repo.get_by_id(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")

    # Suppression des chunks dans pgvector (best-effort)
    try:
        from sqlalchemy import text
        async with session.begin():
            await session.execute(
                text("DELETE FROM documents.embeddings WHERE chunk_id LIKE :prefix"),
                {"prefix": f"doc-{doc_id}-%"}
            )
            await session.execute(
                text("DELETE FROM documents.documents WHERE external_id = :id"),
                {"id": doc_id}
            )
    except Exception as e:
        logger.warning(f"[Documents] Nettoyage pgvector partiel pour {doc_id} : {e}")

    deleted = await _repo.delete(session, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document introuvable")


@router.post("/{doc_id}/reindex", response_model=DocumentUploadResponse, status_code=202,
             summary="Relancer l'indexation d'un document échoué")
async def reindex_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    doc = await _repo.get_by_id(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if doc.status not in (DocumentStatus.FAILED, DocumentStatus.INDEXED):
        raise HTTPException(
            status_code=409,
            detail=f"Le document est en statut {doc.status} — impossible de relancer l'indexation."
        )

    # Pour re-indexer, il faudrait le contenu original. Sans S3 configuré,
    # on ne peut pas le récupérer — on informe l'utilisateur.
    raise HTTPException(
        status_code=501,
        detail="La ré-indexation nécessite que le fichier soit configuré dans S3. "
               "Veuillez re-uploader le document."
    )
