"""
Repository CRUD pour la table `chat_conversations`.
Fournit des fonctions async pour créer, lire, mettre à jour et supprimer
les conversations du chat persistées en base de données.
"""
from __future__ import annotations

from typing import Any, Optional
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict:
    """Convertit une ligne SQLAlchemy en dictionnaire JSON-serializable."""
    return {
        "id":          row.id,
        "title":       row.title,
        "source":      row.source,
        "latency_ms":  row.latency_ms,
        "created_at":  row.created_at.isoformat() if row.created_at else None,
        "group_label": row.group_label,
        "favorite":    row.favorite,
        "trashed":     row.trashed,
    }


# ── CRUD ───────────────────────────────────────────────────────────────────────

async def save_conversation(db: AsyncSession, entry: dict) -> dict:
    """
    Insère une nouvelle conversation ou met à jour son titre/source/latence
    si l'id existe déjà (upsert).
    """
    await db.execute(text("""
        INSERT INTO chat_conversations
            (id, title, source, latency_ms, created_at, group_label, favorite, trashed)
        VALUES
            (:id, :title, :source, :latency_ms, now(), :group_label, FALSE, FALSE)
        ON CONFLICT (id) DO UPDATE
            SET title       = EXCLUDED.title,
                source      = EXCLUDED.source,
                latency_ms  = EXCLUDED.latency_ms,
                group_label = EXCLUDED.group_label
    """), {
        "id":          entry["id"],
        "title":       entry["title"],
        "source":      entry.get("source", ""),
        "latency_ms":  entry.get("latency_ms", 0),
        "group_label": entry.get("group_label", "Aujourd'hui"),
    })
    await db.commit()

    # Re-lire la ligne pour retourner les valeurs réelles (created_at, etc.)
    result = await db.execute(
        text("SELECT * FROM chat_conversations WHERE id = :id"),
        {"id": entry["id"]},
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else entry


async def get_conversations(
    db: AsyncSession,
    limit: int = 100,
    include_trashed: bool = False,
) -> list[dict]:
    """
    Récupère les conversations triées de la plus récente à la plus ancienne.
    Par défaut, les conversations mises à la corbeille sont exclues.
    """
    if include_trashed:
        result = await db.execute(
            text("SELECT * FROM chat_conversations ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit},
        )
    else:
        result = await db.execute(
            text("""
                SELECT * FROM chat_conversations
                WHERE trashed = FALSE
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
    rows = result.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_conversation(
    db: AsyncSession,
    conv_id: str,
    patch: dict,
) -> Optional[dict]:
    """
    Met à jour les champs autorisés d'une conversation :
    title, favorite, trashed.
    Retourne None si l'id n'existe pas.
    """
    allowed_fields = {"title", "favorite", "trashed"}
    updates = {k: v for k, v in patch.items() if k in allowed_fields}

    if not updates:
        return None

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["conv_id"] = conv_id

    await db.execute(
        text(f"UPDATE chat_conversations SET {set_clause} WHERE id = :conv_id"),
        updates,
    )
    await db.commit()

    result = await db.execute(
        text("SELECT * FROM chat_conversations WHERE id = :id"),
        {"id": conv_id},
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else None


async def delete_conversation(db: AsyncSession, conv_id: str) -> bool:
    """
    Supprime définitivement une conversation.
    Retourne True si une ligne a été supprimée, False sinon.
    """
    result = await db.execute(
        text("DELETE FROM chat_conversations WHERE id = :id"),
        {"id": conv_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


# ── Messages ───────────────────────────────────────────────────────────────────

import json as _json


def _msg_row_to_dict(row: Any) -> dict:
    """Convertit une ligne chat_messages en dict JSON-serializable."""
    sources = row.sources
    if isinstance(sources, str):
        try:
            sources = _json.loads(sources)
        except Exception:
            sources = []
    return {
        "id":              row.id,
        "conversation_id": row.conversation_id,
        "role":            row.role,
        "content":         row.content,
        "sources":         sources or [],
        "latency_ms":      row.latency_ms,
        "created_at":      row.created_at.isoformat() if row.created_at else None,
    }


async def save_message(db: AsyncSession, msg: dict) -> dict:
    """
    Insère un message (user ou assistant) dans une conversation.
    msg doit contenir : id, conversation_id, role, content, sources, latency_ms
    """
    await db.execute(text("""
        INSERT INTO chat_messages
            (id, conversation_id, role, content, sources, latency_ms)
        VALUES
            (:id, :conversation_id, :role, :content, CAST(:sources AS JSONB), :latency_ms)
        ON CONFLICT (id) DO NOTHING
    """), {
        "id":              msg["id"],
        "conversation_id": msg["conversation_id"],
        "role":            msg["role"],
        "content":         msg["content"],
        "sources":         _json.dumps(msg.get("sources", [])),
        "latency_ms":      msg.get("latency_ms", 0),
    })
    await db.commit()
    return msg


async def get_messages(db: AsyncSession, conv_id: str) -> list[dict]:
    """
    Retourne tous les messages d'une conversation, du plus ancien au plus récent.
    """
    result = await db.execute(
        text("""
            SELECT * FROM chat_messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at ASC
        """),
        {"conv_id": conv_id},
    )
    rows = result.fetchall()
    return [_msg_row_to_dict(r) for r in rows]
