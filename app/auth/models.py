"""
Schémas Pydantic pour l'authentification — ce qui entre (LoginRequest)
et ce qui sort (UserOut, TokenResponse) des endpoints de app/auth/router.py.

UserOut ne contient JAMAIS hashed_password — c'est la garantie
structurelle (via response_model dans router.py) qu'aucune réponse API
n'expose le hash du mot de passe, même par erreur de code ailleurs.
"""

from uuid import UUID

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Représentation publique d'un utilisateur — jamais de champ
    sensible (hashed_password) ici, volontairement."""

    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    """Réponse renvoyée par /auth/login et /auth/refresh."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut