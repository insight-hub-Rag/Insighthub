"""
Documents Clients — Chunker.

Découpe le texte nettoyé en chunks avec overlap, puis enrichit
les métadonnées de chaque chunk avec les infos du document.
Même logique de chunking récursif que les autres transformers du projet.
"""

import logging
import re
from typing import Optional

from app.core.models import Chunk

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1500
OVERLAP_CHARS = 150


def _recursive_split(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Recursive Character Text Splitting avec overlap (même logique que JiraTransformer)."""
    if len(text) <= max_chars:
        return [text]

    separators = ["\n\n", "\n", ". ", " "]

    def _split(t: str, seps: list[str]) -> list[str]:
        if len(t) <= max_chars:
            return [t]
        sep = seps[0] if seps else " "
        parts = t.split(sep)
        current = ""
        result = []
        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    result.append(current)
                if len(part) > max_chars and len(seps) > 1:
                    result.extend(_split(part, seps[1:]))
                    current = ""
                else:
                    current = part
        if current:
            result.append(current)
        return result

    raw_chunks = _split(text, separators)

    if OVERLAP_CHARS <= 0 or len(raw_chunks) <= 1:
        return raw_chunks

    overlapped = [raw_chunks[0]]
    for i in range(1, len(raw_chunks)):
        prev = raw_chunks[i - 1]
        overlap_text = prev[-OVERLAP_CHARS:] if len(prev) > OVERLAP_CHARS else prev
        overlapped.append(overlap_text + " " + raw_chunks[i])
    return overlapped


def chunk_document(
    doc_id: str,
    filename: str,
    text: str,
    tenant_id: str = "default",
    user_id: Optional[str] = None,
    s3_key: Optional[str] = None,
) -> list[Chunk]:
    """
    Découpe le texte en chunks et construit les objets Chunk prêts à être vectorisés.
    """
    parts = _recursive_split(text)
    chunks = []
    metadata = {
        "filename": filename,
        "tenant_id": tenant_id,
        "user_id": user_id or "",
        "s3_key": s3_key or "",
        "chunk_type": "body",
        "source": "documents",
    }
    for i, part in enumerate(parts):
        chunks.append(Chunk(
            chunk_id=f"doc-{doc_id}-{i}",
            document_id=doc_id,
            source_type="documents",
            content=part,
            metadata={**metadata, "chunk_index": i},
        ))
    logger.info(f"[Chunker] {filename} → {len(chunks)} chunks")
    return chunks
