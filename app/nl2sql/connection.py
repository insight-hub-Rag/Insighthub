"""
app/nl2sql/connection.py

Gestion des connexions SQLAlchemy vers les bases CIBLES (celles que le
NL2SQL Agent interroge), à ne pas confondre avec app/db/database.py qui
gère la connexion vers la base d'InsightHub elle-même.

Phase actuelle : une seule connexion (celle définie dans .env).
Phase future : plusieurs connexions, une par client — c'est pourquoi
rien ici ne dépend directement de `settings`. Tout passe par un
NL2SQLConfig explicite, injecté par l'appelant (orchestrator.py),
qui lui pourra un jour aller chercher cette config ailleurs qu'en
env (table de config, secret manager...) sans que ce fichier change.

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

from app.nl2sql.models import NL2SQLConfig

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

    def get_engine(self, config: NL2SQLConfig) -> Engine:
        if config.connection_id not in self._engines:
            logger.info(
                f"[TargetConnectionManager] Création engine pour "
                f"connection_id='{config.connection_id}'"
            )
            engine = create_engine(
                config.database_url,
                pool_pre_ping=True,   # évite les connexions mortes après idle
                pool_size=5,
                max_overflow=5,
            )
            self._engines[config.connection_id] = engine
            self._session_factories[config.connection_id] = sessionmaker(
                bind=engine, expire_on_commit=False
            )
        return self._engines[config.connection_id]

    @contextmanager
    def get_session(self, config: NL2SQLConfig) -> Iterator[Session]:
        """Session courte durée, à utiliser pour l'exécution des
        requêtes générées — se ferme systématiquement, même en cas
        d'erreur, pour ne jamais laisser une connexion ouverte."""
        self.get_engine(config)  # s'assure que l'engine existe
        session_factory = self._session_factories[config.connection_id]
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