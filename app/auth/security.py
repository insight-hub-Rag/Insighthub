"""
Fonctions cryptographiques pures — hash de mot de passe et JWT.

Ce fichier n'accède jamais à la base de données et ne connaît rien de
FastAPI. Il ne fait que transformer des données : mot de passe en clair
-> hash bcrypt, identité utilisateur -> token JWT signé, et inversement
pour la vérification. Toute la logique "qui a le droit de faire quoi"
vit ailleurs (dependencies.py, router.py).
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

# ---------------------------------------------------------------------
# Mots de passe — bcrypt, jamais de mot de passe stocké en clair.
# CryptContext gère le salage automatique : hash_password() ne renvoie
# jamais deux fois le même résultat pour le même mot de passe.
# ---------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------
# JWT — access token (courte durée, utilisé sur chaque requête API) et
# refresh token (longue durée, cookie httpOnly côté frontend, sert
# uniquement à obtenir un nouvel access token via /auth/refresh).
#
# Le champ "type" (access/refresh) n'est pas standard JWT : on l'ajoute
# nous-mêmes pour empêcher qu'un refresh token soit utilisé directement
# comme access token — dependencies.py vérifie ce champ explicitement.
# ---------------------------------------------------------------------


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": user_id, "role": role, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {"sub": user_id, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Décode et vérifie un token JWT (signature + expiration).

    Lève ValueError si le token est invalide, corrompu, mal signé, ou
    expiré — jamais l'exception jose brute, pour que les appelants
    (dependencies.py, router.py) n'aient qu'un seul type d'erreur à
    gérer, indépendamment de la cause exacte.
    """
    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise ValueError("Token invalide ou expiré") from exc