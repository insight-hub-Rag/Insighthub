import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """
    Force UNE SEULE boucle événementielle asyncio pour toute la session
    de tests, au lieu d'une nouvelle par test (défaut de pytest-asyncio).
    Nécessaire car app/db/database.py crée le moteur de connexion
    (engine, AsyncSessionLocal) UNE FOIS au chargement du module,
    attaché à la boucle active à ce moment-là. Sans ce fixture, chaque
    test async tournerait dans une boucle différente et asyncpg
    refuserait de réutiliser une connexion liée à une autre boucle
    ("attached to a different loop" / "another operation is in progress").
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()