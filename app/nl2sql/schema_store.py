"""
app/nl2sql/schema_store.py

Persistance du schéma scanné — SOURCE DE VÉRITÉ, distincte du cache.
Écrit dans la base InsightHub elle-même (schéma dédié `nl2sql`), jamais
dans la base cible scannée (lecture seule sur la cible, garantie par
connection.py + query_validator.py).

Utilise AsyncSession (app/db/database.py) car il s'agit de la base
InsightHub — cohérent avec le reste du projet, contrairement à
connection.py qui reste synchrone car il cible une base externe.

Une seule table : nl2sql_schema_snapshots. Un scan = une nouvelle ligne
'active', l'ancienne ligne active pour la même connexion passe à
'inactive' — garde un historique complet (utile debug/soutenance),
sans jamais supprimer de données.

Note driver : asyncpg (contrairement à psycopg2) exige un véritable
objet datetime pour une colonne TIMESTAMPTZ — une str ISO lève une
DataError. SchemaScanResult.scanned_at reste une str (format ISO,
portable, facile à logger/débugger) au niveau du modèle métier ; la
conversion str -> datetime est donc une responsabilité de sérialisation
propre à ce store, pas du modèle lui-même.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.nl2sql.models import (
    ColumnInfo,
    ForeignKeyInfo,
    SchemaScanResult,
    TableInfo,
)

logger = logging.getLogger(__name__)


class SchemaStore:
    """
    Un seul backend possible (Postgres/InsightHub) — pas d'abstraction
    ABC ici, seulement une classe concrète injectée dans SchemaCache.
    """

    async def get_active_schema(
        self, session: AsyncSession, connection_id: str
    ) -> SchemaScanResult | None:
        result = await session.execute(
            text(
                """
                SELECT connection_id, engine_dialect, schema_json, scanned_at
                FROM nl2sql_schema_snapshots
                WHERE connection_id = :connection_id AND is_active = TRUE
                ORDER BY scanned_at DESC
                LIMIT 1
                """
            ),
            {"connection_id": connection_id},
        )
        row = result.mappings().first()
        if row is None:
            return None

        return self._deserialize(row)

    async def save_schema(
        self, session: AsyncSession, schema: SchemaScanResult
    ) -> None:
        """Désactive l'ancien snapshot actif puis insère le nouveau,
        dans la même transaction — jamais de trou sans schéma actif."""
        await session.execute(
            text(
                """
                UPDATE nl2sql_schema_snapshots
                SET is_active = FALSE
                WHERE connection_id = :connection_id AND is_active = TRUE
                """
            ),
            {"connection_id": schema.connection_id},
        )

        scanned_at = self._parse_scanned_at(schema.scanned_at)

        await session.execute(
            text(
                """
                INSERT INTO nl2sql_schema_snapshots
                    (connection_id, engine_dialect, schema_json, scanned_at, is_active)
                VALUES
                    (:connection_id, :engine_dialect, :schema_json, :scanned_at, TRUE)
                """
            ),
            {
                "connection_id": schema.connection_id,
                "engine_dialect": schema.engine_dialect,
                "schema_json": json.dumps(self._serialize_tables(schema.tables)),
                "scanned_at": scanned_at,
            },
        )
        await session.commit()

        logger.info(
            f"[SchemaStore] Nouveau snapshot actif enregistré pour "
            f"connection_id='{schema.connection_id}' "
            f"({len(schema.tables)} table(s))"
        )

    # ------------------------------------------------------------
    # Sérialisation — dataclasses imbriquées <-> JSON
    # ------------------------------------------------------------

    @staticmethod
    def _serialize_tables(tables: list[TableInfo]) -> list[dict]:
        return [asdict(table) for table in tables]

    @staticmethod
    def _parse_scanned_at(scanned_at: str | None) -> datetime:
        """Convertit le str ISO du modèle métier en datetime réel,
        requis par asyncpg pour une colonne TIMESTAMPTZ. Fallback sur
        l'heure courante si le champ est absent ou mal formé."""
        if scanned_at:
            try:
                return datetime.fromisoformat(scanned_at)
            except ValueError:
                logger.warning(
                    f"[SchemaStore] scanned_at invalide ('{scanned_at}'), "
                    f"utilisation de l'heure courante."
                )
        return datetime.now(timezone.utc)

    @staticmethod
    def _deserialize(row) -> SchemaScanResult:
        raw_tables = json.loads(row["schema_json"])
        tables = [
            TableInfo(
                name=t["name"],
                schema=t["schema"],
                columns=[ColumnInfo(**c) for c in t["columns"]],
                foreign_keys=[ForeignKeyInfo(**fk) for fk in t["foreign_keys"]],
            )
            for t in raw_tables
        ]
        return SchemaScanResult(
            connection_id=row["connection_id"],
            engine_dialect=row["engine_dialect"],
            tables=tables,
            scanned_at=str(row["scanned_at"]),
        )