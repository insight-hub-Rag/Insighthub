"""
Endpoints d'authentification — assemble security.py + repository.py en
routes HTTP appelables par le frontend.

Le refresh token part en cookie httpOnly (jamais accessible en JS, donc
invulnérable à un vol par script XSS), scopé à /auth/refresh. L'access
token part en JSON, à charge du frontend de le garder en mémoire (pas
en localStorage — voir AuthContext.tsx côté frontend) et de l'attacher
au header Authorization sur chaque requête API.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import LoginRequest, TokenResponse, UserOut
from app.auth.repository import get_user_by_id, get_user_by_email, touch_last_login
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.database import get_db
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 jours, en secondes


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await get_user_by_email(db, payload.email)

    # Message générique volontaire : ne jamais révéler si c'est l'email
    # ou le mot de passe qui est incorrect (empêche un attaquant de
    # découvrir quels emails existent en base en testant des adresses).
    if user is None or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email ou mot de passe incorrect")

    if not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte désactivé")

    access_token = create_access_token(str(user["id"]), user["role"])
    refresh_token = create_refresh_token(str(user["id"]))

    await touch_last_login(db, str(user["id"]))
    await db.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        # Piloté par COOKIE_SECURE (.env) : True en prod (HTTPS obligatoire),
        # False en dev local (http:// sans TLS) — sinon le navigateur/client
        # refuse de renvoyer ce cookie sur /auth/refresh (RFC 6265).
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=REFRESH_COOKIE_MAX_AGE,
        path="/auth/refresh",
    )

    return TokenResponse(access_token=access_token, user=UserOut(**user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pas de session à rafraîchir")

    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise ValueError("Type de token incorrect")
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée, reconnectez-vous")

    user = await get_user_by_id(db, payload["sub"])
    if user is None or not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte désactivé ou introuvable")

    new_access_token = create_access_token(str(user["id"]), user["role"])
    return TokenResponse(access_token=new_access_token, user=UserOut(**user))


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie("refresh_token", path="/auth/refresh")
    return {"success": True}


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(**user)