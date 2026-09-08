"""
Schémas Pydantic pour l'administration des comptes utilisateurs — la
page "Utilisateurs" de la sidebar (visible uniquement pour un admin).

Contrairement à app/auth/models.py (UserOut, utilisé par le compte QUI
EST connecté pour se voir lui-même), UserSummary sert à un admin qui
liste TOUS les comptes — même absence volontaire de hashed_password.
"""

from typing import Optional
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UserSummary(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """Tous les champs optionnels — PATCH partiel, seuls les champs
    fournis sont modifiés (même logique que ConnectorUpdate déjà vu
    dans app/admin/connectors/models.py)."""

    role: Optional[str] = None
    is_active: Optional[bool] = None