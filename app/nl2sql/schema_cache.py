"""
app/nl2sql/schema_cache.py

Cache de performance au-dessus de SchemaStore (source de vérité
persistante). Implémente le Cache-Aside Pattern : lecture cache
d'abord, fallback vers le store en cas de miss/expiration, puis
repopulation du cache.

Strategy Pattern : SchemaCache est une ABC, deux implémentations
concrètes (in-memory pour dev/test, Redis pour prod/multi-instance).
Le choix du backend est piloté par config,
jamais par un if/elif dans le code métier.

Le cache ne remplace jamais le store — si le cache est vidé (redémarrage,
éviction TTL, changement de nœud), les données ne sont pas perdues,
elles sont simplement re-lues depuis nl2sql_schema_snapshots.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.nl2sql.models import ColumnInfo, ForeignKeyInfo, SchemaScanResult, TableInfo
from app.nl2sql.schema_store import SchemaStore

logger = logging.getLogger(__name__)


class SchemaCache(ABC):
    """
    Contrat pour un backend de cache de schéma. Ne connaît jamais
    SQLAlchemy ni le store directement au niveau de l'interface — les
    méthodes abstraites manipulent uniquement des SchemaScanResult.
    """

    def __init__(self, store: SchemaStore, ttl_seconds: int = 86400):
        self._store = store
        self._ttl_seconds = ttl_seconds

    @abstractmethod
    async def _get_raw(self, connection_id: str) -> tuple[SchemaScanResult, float] | None:
        """Retourne (schema, cached_at_timestamp) ou None si absent."""
        ...

    @abstractmethod
    async def _set_raw(self, connection_id: str, schema: SchemaScanResult) -> None:
        ...

    @abstractmethod
    async def invalidate(self, connection_id: str) -> None:
        ...

    async def get_or_load(
        self, session: AsyncSession, connection_id: str
    ) -> SchemaScanResult | None:
        """
        Point d'entrée unique utilisé par le reste du pipeline
        (query_generator.py). Gère TTL + fallback store de façon
        transparente pour l'appelant.
        """
        cached = await self._get_raw(connection_id)
        if cached is not None:
            schema, cached_at = cached
            if (time.time() - cached_at) < self._ttl_seconds:
                logger.debug(f"[SchemaCache] Hit pour '{connection_id}'")
                return schema
            logger.info(f"[SchemaCache] Expiré pour '{connection_id}', fallback store")

        schema = await self._store.get_active_schema(session, connection_id)
        if schema is not None:
            await self._set_raw(connection_id, schema)
            logger.info(f"[SchemaCache] Repopulé depuis le store pour '{connection_id}'")

        return schema

    async def refresh(
        self, session: AsyncSession, schema: SchemaScanResult
    ) -> None:
        """
        Appelé après un nouveau scan (rescan manuel ou automatique) :
        persiste dans le store ET met à jour le cache immédiatement,
        pour ne pas attendre le prochain miss.
        """
        await self._store.save_schema(session, schema)
        await self._set_raw(schema.connection_id, schema)
        logger.info(f"[SchemaCache] Rafraîchi (store + cache) pour '{schema.connection_id}'")


# ==================================================================
# Implémentation 1 — In-memory (dev / tests / single-instance)
# ==================================================================

class InMemorySchemaCache(SchemaCache):

    def __init__(self, store: SchemaStore, ttl_seconds: int = 86400):
        super().__init__(store, ttl_seconds)
        self._data: dict[str, tuple[SchemaScanResult, float]] = {}

    async def _get_raw(self, connection_id: str) -> tuple[SchemaScanResult, float] | None:
        return self._data.get(connection_id)

    async def _set_raw(self, connection_id: str, schema: SchemaScanResult) -> None:
        self._data[connection_id] = (schema, time.time())

    async def invalidate(self, connection_id: str) -> None:
        self._data.pop(connection_id, None)


# ==================================================================
# Implémentation 2 — Redis (prod / multi-instance)
# ==================================================================

class RedisSchemaCache(SchemaCache):

    _KEY_PREFIX = "nl2sql:schema:"

    def __init__(self, store: SchemaStore, redis_client, ttl_seconds: int = 86400):
        super().__init__(store, ttl_seconds)
        self._redis = redis_client

    def _key(self, connection_id: str) -> str:
        return f"{self._KEY_PREFIX}{connection_id}"

    async def _get_raw(self, connection_id: str) -> tuple[SchemaScanResult, float] | None:
        raw = await self._redis.get(self._key(connection_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        schema = self._deserialize(payload["schema"])
        return schema, payload["cached_at"]

    async def _set_raw(self, connection_id: str, schema: SchemaScanResult) -> None:
        payload = json.dumps({
            "schema": self._serialize(schema),
            "cached_at": time.time(),
        })
        # expire côté Redis en plus du TTL applicatif, en filet de sécurité
        await self._redis.set(self._key(connection_id), payload, ex=self._ttl_seconds * 2)

    async def invalidate(self, connection_id: str) -> None:
        await self._redis.delete(self._key(connection_id))

    @staticmethod
    def _serialize(schema: SchemaScanResult) -> dict:
        return {
            "connection_id": schema.connection_id,
            "engine_dialect": schema.engine_dialect,
            "scanned_at": schema.scanned_at,
            "tables": [asdict(t) for t in schema.tables],
        }

    @staticmethod
    def _deserialize(payload: dict) -> SchemaScanResult:
        tables = [
            TableInfo(
                name=t["name"],
                schema=t["schema"],
                columns=[ColumnInfo(**c) for c in t["columns"]],
                foreign_keys=[ForeignKeyInfo(**fk) for fk in t["foreign_keys"]],
            )
            for t in payload["tables"]
        ]
        return SchemaScanResult(
            connection_id=payload["connection_id"],
            engine_dialect=payload["engine_dialect"],
            tables=tables,
            scanned_at=payload["scanned_at"],
        )