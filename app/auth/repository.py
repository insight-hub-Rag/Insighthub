"""
Accès base de données pour l'authentification — requêtes SQL brutes sur
`public.users`, cohérent avec le reste du projet (voir
app/admin/connectors/repository.py, même approche, aucun ORM).

Ne connaît rien de la sécurité (hash, JWT) ni de FastAPI — juste des
lectures/écritures de lignes. security.py et router.py orchestrent
l'appel de ces fonctions.
"""

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[dict[str, Any]]:
    """Utilisée à la connexion — l'utilisateur ne connaît que son email."""
    result = await session.execute(
        text("SELECT * FROM public.users WHERE email = :email"),
        {"email": email},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_by_id(session: AsyncSession, user_id: str) -> Optional[dict[str, Any]]:
    """Utilisée partout après authentification — on ne manipule plus que
    l'UUID extrait du champ "sub" du token JWT."""
    result = await session.execute(
        text("SELECT * FROM public.users WHERE id = :id"),
        {"id": user_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def touch_last_login(session: AsyncSession, user_id: str) -> None:
    """Met à jour la date de dernière connexion — appelée après un login
    réussi. Ne fait pas son propre commit : c'est router.py qui commit,
    dans la même transaction que le reste du flux de login."""
    await session.execute(
        text("UPDATE public.users SET last_login_at = now() WHERE id = :id"),
        {"id": user_id},
    )