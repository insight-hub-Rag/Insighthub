"""
app/nl2sql/connection.py

Gestion des connexions SQLAlchemy vers les bases CIBLES (celles que le
NL2SQL Agent interroge), à ne pas confondre avec app/db/database.py qui
gère la connexion vers la base d'InsightHub elle-même.

CORRECTIF : get_engine/get_session prenaient un NL2SQLConfig complet
avec connection_id figé ("default"). Ils prennent maintenant
connection_id et database_url séparément, passés explicitement par
l'appelant (orchestrator.py) à chaque question, résolus dynamiquement
depuis la base SQL actuellement active — plus aucune valeur figée.

Connexions synchrones (pas asyncpg) : l'introspection SQLAlchemy
(`inspect()`) et l'exécution de requêtes générées dynamiquement sont
plus simples et plus prévisibles en synchrone ici — ce module tourne
dans un thread pool via asyncio.to_thread() côté orchestrator, pour ne
pas bloquer l'event loop FastAPI.
"""

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class TargetConnectionManager:
    """
    Fabrique et met en cache un engine SQLAlchemy par connection_id.
    Un seul engine par connexion cible pour toute la durée de vie de
    l'app (pool de connexions réutilisé), plutôt qu'un engine recréé
    à chaque question — coûteux et inutile.
    """

    def __init__(self):
        self._engines: dict[str, Engine] = {}
        self._session_factories: dict[str, sessionmaker] = {}

    def get_engine(self, connection_id: str, database_url: str) -> Engine:
        if connection_id not in self._engines:
            logger.info(
                f"[TargetConnectionManager] Création engine pour "
                f"connection_id='{connection_id}'"
            )
            if database_url.startswith("sqlite"):
                import sqlite3
                db_path = database_url.replace("sqlite:///", "")
                if "?" in db_path:
                    db_path = db_path.split("?")[0]
                creator = lambda: sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                engine = create_engine(
                    "sqlite://",
                    creator=creator
                )
            else:
                engine = create_engine(
                    database_url,
                    pool_pre_ping=True,   # évite les connexions mortes après idle
                    pool_size=5,
                    max_overflow=5,
                )
            self._engines[connection_id] = engine
            self._session_factories[connection_id] = sessionmaker(
                bind=engine, expire_on_commit=False
            )
        return self._engines[connection_id]

    @contextmanager
    def get_session(self, connection_id: str, database_url: str) -> Iterator[Session]:
        """Session courte durée, à utiliser pour l'exécution des
        requêtes générées — se ferme systématiquement, même en cas
        d'erreur, pour ne jamais laisser une connexion ouverte."""
        self.get_engine(connection_id, database_url)  # s'assure que l'engine existe
        session_factory = self._session_factories[connection_id]
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self, connection_id: str) -> None:
        """Ferme et retire l'engine d'une connexion — utile si une
        config de connexion change (nouvelle URL pour le même client)."""
        engine = self._engines.pop(connection_id, None)
        self._session_factories.pop(connection_id, None)
        if engine is not None:
            engine.dispose()
            logger.info(
                f"[TargetConnectionManager] Engine disposé pour "
                f"connection_id='{connection_id}'"
            )


# Instance unique partagée — cohérent avec le pattern déjà utilisé pour
# _orchestrator dans app/api/router.py (une seule instance réutilisée
# entre les requêtes, pas recréée à chaque appel).
target_connection_manager = TargetConnectionManager()