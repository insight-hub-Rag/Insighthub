import logging
import time
import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.connectors.jira.pipeline import JiraConnector
from app.connectors.jira.transformer import JiraTransformer
from app.db.vector_store import VectorStore
from app.ingestion.embeddings.embedder import Embedder
from app.ingestion.pipeline import IngestionPipeline
from app.rag.retriever import Retriever
from app.rag.generator import Generator

logger = logging.getLogger(__name__)
router = APIRouter()


class SyncRequest(BaseModel):
    project_key:   Optional[str] = None
    updated_after: Optional[str] = None


class SearchRequest(BaseModel):
    question:       str
    source:         Optional[str]   = None
    top_k:          Optional[int]   = None
    min_similarity: Optional[float] = None
    generate:       bool            = True


def _build_jira_pipeline(request: SyncRequest) -> IngestionPipeline:
    return IngestionPipeline(
        connector   = JiraConnector(project_key=request.project_key),
        transformer = JiraTransformer(),
        embedder    = Embedder(),
        store       = VectorStore(),
    )


PIPELINE_FACTORIES = {
    "jira": _build_jira_pipeline,
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


@router.post("/search", summary="Recherche sémantique RAG")
async def search(request: SearchRequest) -> dict:
    t_start = time.time()

    try:
        retriever   = Retriever()
        chunks      = retriever.search(
            query          = request.question,
            source         = request.source,
            top_k          = request.top_k,
            min_similarity = request.min_similarity,
        )
        t_retrieval = time.time() - t_start

        if not request.generate:
            return {
                "question": request.question,
                "chunks":   [
                    {
                        "chunk_id":    c.chunk_id,
                        "source_type": c.source_type,
                        "document_id": c.document_id,
                        "title":       c.title,
                        "similarity":  c.similarity,
                        "content":     c.content[:300],
                    }
                    for c in chunks
                ],
                "performance": {
                    "retrieval_ms": round(t_retrieval * 1000, 1),
                    "chunks_found": len(chunks),
                },
            }

        t_gen_start = time.time()
        generator   = Generator()
        response    = generator.generate(request.question, chunks)
        t_gen       = time.time() - t_gen_start
        t_total     = time.time() - t_start

        return {
            "question":              response.question,
            "answer":                response.answer,
            "model":                 response.model,
            "sources":               response.sources,
            "total_chunks_searched": response.total_chunks_searched,
            "performance": {
                "retrieval_ms":  round(t_retrieval * 1000, 1),
                "generation_ms": round(t_gen * 1000, 1),
                "total_ms":      round(t_total * 1000, 1),
            },
        }

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc