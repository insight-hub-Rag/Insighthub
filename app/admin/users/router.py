"""
Administration des comptes utilisateurs — GET /users (liste) et
PATCH /users/{id} (rôle, activation). Réservé aux admins via
require_role("admin").

Volontairement pas d'endpoint de création ici : créer un compte depuis
une interface web nécessiterait de gérer l'envoi sécurisé d'un mot de
passe initial (email d'invitation...), hors sujet pour l'instant — la
création reste au script scripts/create_user.py.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.database import get_db
from app.admin.users.models import UserSummary, UserUpdate

router = APIRouter(prefix="/users", tags=["admin-users"])


@router.get("", response_model=list[UserSummary])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_role("admin")),
) -> list[UserSummary]:
    result = await db.execute(
        text("SELECT id, email, full_name, role, is_active, created_at FROM public.users ORDER BY role, full_name")
    )
    rows = result.mappings().all()
    return [UserSummary(**dict(row)) for row in rows]


@router.patch("/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: dict[str, Any] = Depends(require_role("admin")),
) -> UserSummary:
    # Un admin ne peut jamais modifier son propre rôle ou se désactiver
    # lui-même — évite qu'une erreur de manipulation le bloque hors de
    # l'application, sans personne d'autre pour le réactiver.
    if str(admin["id"]) == user_id:
        if payload.role is not None and payload.role != admin["role"]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Vous ne pouvez pas modifier votre propre rôle",
            )
        if payload.is_active is False:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Vous ne pouvez pas désactiver votre propre compte",
            )

    updates: dict[str, Any] = {}
    if payload.role is not None:
        updates["role"] = payload.role
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucun champ à mettre à jour")

    set_clause = ", ".join(f"{key} = :{key}" for key in updates)
    result = await db.execute(
        text(f"""
            UPDATE public.users
            SET {set_clause}
            WHERE id = :user_id
            RETURNING id, email, full_name, role, is_active, created_at
        """),
        {**updates, "user_id": user_id},
    )
    row = result.mappings().first()
    await db.commit()

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable")

    return UserSummary(**dict(row))