"""
Documents Clients — modèles Pydantic pour l'API.

Représentent les documents uploadés par les utilisateurs (PDF, DOCX, TXT, CSV, PPTX).
Le cycle de vie d'un document suit le statut :
  UPLOADING → UPLOADED → PROCESSING → INDEXED  (ou FAILED)
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class DocumentStatus(str, Enum):
    UPLOADING   = "UPLOADING"
    UPLOADED    = "UPLOADED"
    PROCESSING  = "PROCESSING"
    INDEXED     = "INDEXED"
    FAILED      = "FAILED"


class DocumentOut(BaseModel):
    """Document renvoyé par l'API (liste + détail)."""
    id:           str
    filename:     str
    file_type:    str
    file_size:    int           # en octets
    status:       DocumentStatus
    chunk_count:  int
    tenant_id:    str
    user_id:      Optional[str]
    s3_key:       Optional[str]
    error:        Optional[str]
    created_at:   datetime
    updated_at:   datetime


class DocumentUploadResponse(BaseModel):
    """Réponse immédiate après upload (avant indexation)."""
    document_id: str
    filename:    str
    status:      DocumentStatus
    message:     str
