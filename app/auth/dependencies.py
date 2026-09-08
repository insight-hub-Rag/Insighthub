"""
Dépendances FastAPI pour l'authentification — à brancher via Depends(...)
sur n'importe quelle route à protéger.

get_current_user : vérifie le token d'accès et renvoie l'utilisateur
courant. La brancher sur un endpoint (ou globalement sur un router,
voir main.py) suffit à exiger une authentification valide.

require_admin : en plus de get_current_user, exige que l'utilisateur
ait le rôle "admin". Réutilisable pour toute route réservée aux admins.
"""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import get_user_by_id
from app.auth.security import decode_token
from app.db.database import get_db

# auto_error=False : on gère nous-mêmes l'absence de token (401 avec un
# message explicite), plutôt que de laisser FastAPI renvoyer un 403
# générique avant même que notre code ne s'exécute.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non authentifié")

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            # Empêche qu'un refresh token (longue durée, cookie httpOnly)
            # soit utilisé directement comme token d'accès sur l'API.
            raise ValueError("Type de token incorrect")
    except ValueError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session expirée, reconnectez-vous"
        )

    user = await get_user_by_id(db, payload["sub"])
    if user is None or not user["is_active"]:
        # Vérifié en base à CHAQUE requête, pas seulement au login : un
        # compte désactivé entre-temps ne doit pas continuer à
        # fonctionner juste parce que son token n'est pas encore expiré.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Utilisateur inactif ou introuvable"
        )
    return user


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs")
    return user


def require_role(*allowed_roles: str):
    """Garde-fou générique, paramétré par la liste des rôles autorisés.

    Usage : dependencies=[Depends(require_role("admin", "rh"))] sur une
    route réservée à plusieurs rôles à la fois. require_admin ci-dessus
    reste la version pratique pour le cas le plus courant (admin seul),
    les deux partagent la même logique — aucune duplication.
    """

    def dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès refusé pour ce rôle")
        return user

    return dependency