"""
Chiffrement des credentials des connecteurs (URL, email, token API...)

"""

import json
from functools import lru_cache

from cryptography.fernet import Fernet

from config import settings


class ConnectorCredentialsError(Exception):
    """Levée si la clé de chiffrement est absente ou invalide."""


@lru_cache
def _fernet() -> Fernet:
    if not settings.connector_encryption_key:
        raise ConnectorCredentialsError(
            "CONNECTOR_ENCRYPTION_KEY n'est pas configurée. Génère une clé "
            "avec : python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" et mets-la dans .env"
        )
    return Fernet(settings.connector_encryption_key.encode())


def encrypt_auth_fields(auth_fields: dict[str, str]) -> str:
    """dict en clair (ex: {"url": "...", "email": "...", "token": "..."})
    -> chaîne chiffrée, prête à stocker dans connector_configs.auth_encrypted."""
    raw = json.dumps(auth_fields).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_auth_fields(auth_encrypted: str) -> dict[str, str]:
    """Chaîne chiffrée -> dict en clair, pour appeler les vraies API."""
    raw = _fernet().decrypt(auth_encrypted.encode())
    return json.loads(raw)


MASK_PLACEHOLDER = "•" * 12
_SECRET_FIELD_NAMES = ("token", "api_token", "password", "client_secret", "secret")


def mask_auth_fields(auth_fields: dict[str, str]) -> dict[str, str]:
    """Pour l'affichage côté UI : garde les champs non sensibles tels
    quels (url, email), masque tout ce qui ressemble à un secret."""
    masked = {}
    for key, value in auth_fields.items():
        if key.lower() in _SECRET_FIELD_NAMES:
            masked[key] = MASK_PLACEHOLDER
        else:
            masked[key] = value
    return masked