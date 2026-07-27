

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class DuplicateInstanceLabelError(Exception):
    """Levée quand (source_type, instance_label) existe déjà — au lieu
    de laisser remonter une IntegrityError brute jusqu'à un 500 HTTP
    générique et incompréhensible côté frontend."""


class ConnectorRepository:

    async def list_all(self, session: AsyncSession) -> list[dict[str, Any]]:
        result = await session.execute(
            text("SELECT * FROM connector_configs ORDER BY source_type, instance_label")
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_by_id(
        self, session: AsyncSession, connector_id: UUID
    ) -> Optional[dict[str, Any]]:
        result = await session.execute(
            text("SELECT * FROM connector_configs WHERE id = :id"),
            {"id": str(connector_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def create(
        self,
        session: AsyncSession,
        source_type: str,
        instance_label: str,
        auth_encrypted: str,
        sync_scope: dict[str, Any],
        sync_frequency_minutes: int,
    ) -> dict[str, Any]:
        try:
            result = await session.execute(
                text(
                    """
                    INSERT INTO connector_configs
                        (source_type, instance_label, auth_encrypted, sync_scope, sync_frequency_minutes)
                    VALUES
                        (:source_type, :instance_label, :auth_encrypted, :sync_scope, :sync_frequency_minutes)
                    RETURNING *
                    """
                ),
                {
                    "source_type": source_type,
                    "instance_label": instance_label,
                    "auth_encrypted": auth_encrypted,
                    "sync_scope": _to_json(sync_scope),
                    "sync_frequency_minutes": sync_frequency_minutes,
                },
            )
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            if "connector_configs_source_type_instance_label_key" in str(e.orig):
                raise DuplicateInstanceLabelError(
                    f"Une instance {source_type} nommée '{instance_label}' existe déjà."
                ) from e
            raise
        return dict(result.mappings().first())
        return dict(result.mappings().first())

    async def update(
        self, session: AsyncSession, connector_id: UUID, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """`fields` ne contient que les colonnes à modifier (PATCH
        partiel) — construit dynamiquement, mais uniquement à partir de
        noms de colonnes whitelistés par service.py, jamais depuis une
        entrée utilisateur brute (protection injection SQL)."""
        if not fields:
            return await self.get_by_id(session, connector_id)

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = {**fields, "id": str(connector_id), }

        try:
            result = await session.execute(
                text(
                    f"""
                    UPDATE connector_configs
                    SET {set_clause}, updated_at = now()
                    WHERE id = :id
                    RETURNING *
                    """
                ),
                params,
            )
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            if "connector_configs_source_type_instance_label_key" in str(e.orig):
                raise DuplicateInstanceLabelError(
                    "Une instance avec ce nom existe déjà pour cette source."
                ) from e
            raise
        row = result.mappings().first()
        return dict(row) if row else None

    async def record_sync_result(
        self,
        session: AsyncSession,
        connector_id: UUID,
        success: bool,
        stats: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Appelé après une synchronisation (manuelle ou déclenchée par
        Lambda/EventBridge) pour mettre à jour last_sync_*."""
        await session.execute(
            text(
                """
                UPDATE connector_configs
                SET last_sync_at = now(),
                    last_sync_status = :status,
                    last_sync_stats = :stats,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": str(connector_id),
                "status": "success" if success else "error",
                "stats": _to_json(stats) if stats else None,
                "error": error,
            },
        )
        await session.commit()

    async def delete(self, session: AsyncSession, connector_id: UUID) -> bool:
        result = await session.execute(
            text("DELETE FROM connector_configs WHERE id = :id"),
            {"id": str(connector_id)},
        )
        await session.commit()
        return result.rowcount > 0


def _to_json(value: dict[str, Any]) -> str:
    import json
    return json.dumps(value)