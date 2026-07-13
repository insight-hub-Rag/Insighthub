"""
app/nl2sql/schema_scanner.py

Introspection du schéma d'une base cible via SQLAlchemy `inspect()`.
Produit un SchemaScanResult complet (tables, colonnes, types, clés
primaires, clés étrangères) — indépendant du moteur SQL sous-jacent,
SQLAlchemy abstrait déjà PostgreSQL / MySQL / Oracle / SQL Server au
niveau de l'inspection.

Ce module ne fait QUE scanner — il ne décide pas de la fréquence de
scan (schema_cache.py) ni de la persistance (schema_store.py). SRP
strict : une seule responsabilité, lire le schéma réel à l'instant T.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import Engine, inspect

from app.nl2sql.models import ColumnInfo, ForeignKeyInfo, SchemaScanResult, TableInfo

logger = logging.getLogger(__name__)

EXCLUDED_TABLES = {"alembic_version", "spatial_ref_sys"}


class SchemaScanner:

    def scan(self, engine: Engine, connection_id: str) -> SchemaScanResult:
        inspector = inspect(engine)
        dialect_name = engine.dialect.name

        tables: list[TableInfo] = []

        for schema_name in self._resolve_schemas(inspector):
            for table_name in inspector.get_table_names(schema=schema_name):
                if table_name in EXCLUDED_TABLES:
                    continue
                tables.append(
                    self._scan_table(inspector, table_name, schema_name)
                )

        result = SchemaScanResult(
            connection_id=connection_id,
            engine_dialect=dialect_name,
            tables=tables,
            scanned_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            f"[SchemaScanner] connection_id='{connection_id}' "
            f"dialect='{dialect_name}' → {len(tables)} table(s) scannée(s)"
        )
        return result

    def _resolve_schemas(self, inspector) -> list[str | None]:
        default_schema = inspector.default_schema_name
        return [default_schema]

    def _scan_table(self, inspector, table_name: str, schema_name: str | None) -> TableInfo:
        pk_constraint = inspector.get_pk_constraint(table_name, schema=schema_name)
        pk_columns = set(pk_constraint.get("constrained_columns") or [])

        columns = [
            ColumnInfo(
                name=col["name"],
                data_type=str(col["type"]),
                nullable=col.get("nullable", True),
                is_primary_key=col["name"] in pk_columns,
                default=self._safe_default(col.get("default")),
            )
            for col in inspector.get_columns(table_name, schema=schema_name)
        ]

        foreign_keys = [
            ForeignKeyInfo(
                column=fk["constrained_columns"][0],
                references_table=fk["referred_table"],
                references_column=fk["referred_columns"][0],
            )
            for fk in inspector.get_foreign_keys(table_name, schema=schema_name)
            if fk.get("constrained_columns") and fk.get("referred_columns")
        ]

        return TableInfo(
            name=table_name,
            schema=schema_name or "public",
            columns=columns,
            foreign_keys=foreign_keys,
        )

    @staticmethod
    def _safe_default(default) -> str | None:
        return str(default) if default is not None else None