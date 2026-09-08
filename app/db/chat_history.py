"""
Repository CRUD pour la table `chat_conversations`.
Fournit des fonctions async pour créer, lire, mettre à jour et supprimer
les conversations du chat persistées en base de données.

Toute fonction touchant une conversation ou ses messages exige désormais
un user_id, et filtre/vérifie l'appartenance à chaque requête — jamais
seulement pour l'affichage : un UPDATE/DELETE qui ne cible pas la bonne
ligne à cause d'un user_id différent ne touche silencieusement aucune
ligne, empêchant qu'un utilisateur modifie ou supprime une conversation
qui ne lui appartient pas, même en devinant son id (les id de
conversation ne sont pas des secrets, juste des identifiants techniques).
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

async def save_conversation(db: AsyncSession, user_id: str, entry: dict) -> dict:
    """
    Insère une nouvelle conversation ou met à jour son titre/source/latence
    si l'id existe déjà (upsert). user_id n'est jamais réécrit par le
    ON CONFLICT — le propriétaire d'une conversation ne change pas.
    """
    await db.execute(text("""
        INSERT INTO chat_conversations
            (id, user_id, title, source, latency_ms, created_at, group_label, favorite, trashed)
        VALUES
            (:id, :user_id, :title, :source, :latency_ms, now(), :group_label, FALSE, FALSE)
        ON CONFLICT (id) DO UPDATE
            SET title       = EXCLUDED.title,
                source      = EXCLUDED.source,
                latency_ms  = EXCLUDED.latency_ms,
                group_label = EXCLUDED.group_label
    """), {
        "id":          entry["id"],
        "user_id":     user_id,
        "title":       entry["title"],
        "source":      entry.get("source", ""),
        "latency_ms":  entry.get("latency_ms", 0),
        "group_label": entry.get("group_label", "Aujourd'hui"),
    })
    await db.commit()

    # Re-lire la ligne pour retourner les valeurs réelles (created_at, etc.)
    result = await db.execute(
        text("SELECT * FROM chat_conversations WHERE id = :id AND user_id = :user_id"),
        {"id": entry["id"], "user_id": user_id},
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else entry


async def get_conversations(
    db: AsyncSession,
    user_id: str,
    limit: int = 100,
    include_trashed: bool = False,
) -> list[dict]:
    """
    Récupère les conversations de user_id, triées de la plus récente à la
    plus ancienne. Par défaut, les conversations mises à la corbeille sont
    exclues.
    """
    if include_trashed:
        result = await db.execute(
            text("""
                SELECT * FROM chat_conversations
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"user_id": user_id, "limit": limit},
        )
    else:
        result = await db.execute(
            text("""
                SELECT * FROM chat_conversations
                WHERE user_id = :user_id AND trashed = FALSE
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"user_id": user_id, "limit": limit},
        )
    rows = result.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_conversation(
    db: AsyncSession,
    conv_id: str,
    user_id: str,
    patch: dict,
) -> Optional[dict]:
    """
    Met à jour les champs autorisés d'une conversation appartenant à
    user_id : title, favorite, trashed.
    Retourne None si l'id n'existe pas OU n'appartient pas à user_id —
    les deux cas sont volontairement indistinguables côté appelant (pas
    de fuite d'information sur l'existence d'une conversation d'autrui).
    """
    allowed_fields = {"title", "favorite", "trashed"}
    updates = {k: v for k, v in patch.items() if k in allowed_fields}

    if not updates:
        return None

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["conv_id"] = conv_id
    updates["user_id"] = user_id

    await db.execute(
        text(f"UPDATE chat_conversations SET {set_clause} WHERE id = :conv_id AND user_id = :user_id"),
        updates,
    )
    await db.commit()

    result = await db.execute(
        text("SELECT * FROM chat_conversations WHERE id = :id AND user_id = :user_id"),
        {"id": conv_id, "user_id": user_id},
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else None


async def delete_conversation(db: AsyncSession, conv_id: str, user_id: str) -> bool:
    """
    Supprime définitivement une conversation appartenant à user_id.
    Retourne True si une ligne a été supprimée, False sinon (id
    inexistant ou appartenant à un autre utilisateur).
    """
    result = await db.execute(
        text("DELETE FROM chat_conversations WHERE id = :id AND user_id = :user_id"),
        {"id": conv_id, "user_id": user_id},
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


async def save_message(db: AsyncSession, user_id: str, msg: dict) -> Optional[dict]:
    """
    Insère un message (user ou assistant) dans une conversation, après
    avoir vérifié qu'elle appartient bien à user_id — chat_messages n'a
    pas sa propre colonne user_id (un message appartient à une
    conversation, qui elle appartient à un utilisateur), donc la
    vérification passe par une requête de contrôle avant l'INSERT plutôt
    qu'un filtre direct dessus.
    Retourne None (sans rien insérer) si la conversation n'appartient
    pas à user_id ou n'existe pas.
    msg doit contenir : id, conversation_id, role, content, sources, latency_ms
    """
    owner_check = await db.execute(
        text("SELECT 1 FROM chat_conversations WHERE id = :conv_id AND user_id = :user_id"),
        {"conv_id": msg["conversation_id"], "user_id": user_id},
    )
    if owner_check.fetchone() is None:
        return None

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


async def get_messages(db: AsyncSession, user_id: str, conv_id: str) -> list[dict]:
    """
    Retourne tous les messages d'une conversation appartenant à user_id,
    du plus ancien au plus récent. La jointure sur chat_conversations
    fait à la fois le filtrage ET la vérification d'appartenance : si
    conv_id n'existe pas ou appartient à un autre utilisateur, la liste
    revient naturellement vide, sans code de contrôle séparé.
    """
    result = await db.execute(
        text("""
            SELECT m.* FROM chat_messages m
            JOIN chat_conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = :conv_id AND c.user_id = :user_id
            ORDER BY m.created_at ASC
        """),
        {"conv_id": conv_id, "user_id": user_id},
    )
    rows = result.fetchall()
    return [_msg_row_to_dict(r) for r in rows]