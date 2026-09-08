"""
Requêtes d'agrégation pour le Dashboard global.

Contrairement à app/db/chat_history.py (filtré par utilisateur, pour le
chat personnel), ce module ne filtre jamais par user_id — c'est une vue
d'ensemble de toute la plateforme, réservée aux admins (voir router.py).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Schémas contenant des documents indexés — un par source RAG documentaire.
# NL2SQL (bases SQL externes) n'a pas de "documents" au même sens, donc
# volontairement absent de cette liste.
_DOCUMENT_SCHEMAS = ["jira", "confluence", "sharepoint", "servicenow", "documents"]


def _trend_pct(current: float, previous: Optional[float]) -> Optional[float]:
    """Variation en % entre la période précédente et la période courante.
    None si la période précédente est vide (rien à comparer)."""
    if previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


async def count_questions(db: AsyncSession, since: datetime, until: Optional[datetime] = None) -> int:
    if until is None:
        result = await db.execute(
            text("SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= :since"),
            {"since": since},
        )
    else:
        result = await db.execute(
            text("SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= :since AND created_at < :until"),
            {"since": since, "until": until},
        )
    return result.scalar_one()


async def count_active_users(db: AsyncSession, since: datetime, until: Optional[datetime] = None) -> int:
    if until is None:
        result = await db.execute(
            text("SELECT COUNT(DISTINCT user_id) FROM chat_conversations WHERE created_at >= :since AND user_id IS NOT NULL"),
            {"since": since},
        )
    else:
        # Requête sur une fenêtre bornée, nécessaire pour la période
        # précédente : un COUNT(DISTINCT ...) ne peut PAS se déduire par
        # soustraction de deux comptages (contrairement à un COUNT(*))
        # — un même utilisateur actif sur les deux périodes fausserait
        # le résultat si on essayait de soustraire.
        result = await db.execute(
            text("SELECT COUNT(DISTINCT user_id) FROM chat_conversations WHERE created_at >= :since AND created_at < :until AND user_id IS NOT NULL"),
            {"since": since, "until": until},
        )
    return result.scalar_one()


async def average_confidence(db: AsyncSession, since: datetime, until: Optional[datetime] = None) -> Optional[float]:
    """Moyenne du meilleur score de chaque réponse assistant sur la
    période — un score par réponse (pas par source individuelle), pour
    ne pas favoriser artificiellement les réponses à beaucoup de sources."""
    until_clause = "AND created_at < :until" if until is not None else ""
    params = {"since": since}
    if until is not None:
        params["until"] = until

    result = await db.execute(
        text(f"""
            SELECT AVG(best_score) FROM (
                SELECT (
                    SELECT MAX((elem->>'score')::float)
                    FROM jsonb_array_elements(sources) elem
                ) AS best_score
                FROM chat_messages
                WHERE role = 'assistant'
                  AND created_at >= :since
                  {until_clause}
                  AND jsonb_array_length(sources) > 0
            ) scored
            WHERE best_score IS NOT NULL
        """),
        params,
    )
    value = result.scalar_one_or_none()
    return round(float(value) * 100, 1) if value is not None else None


async def count_indexed_documents(db: AsyncSession) -> int:
    """Total toutes sources confondues — pas de notion de période ici,
    c'est un instantané de l'état actuel de l'index, pas une activité
    datée comme les autres KPI."""
    parts = " + ".join(f"(SELECT COUNT(*) FROM {schema}.documents)" for schema in _DOCUMENT_SCHEMAS)
    result = await db.execute(text(f"SELECT {parts} AS total"))
    return result.scalar_one() or 0


async def questions_per_day(db: AsyncSession, days: int = 7) -> list[dict]:
    """Nombre de questions posées par jour, sur les `days` derniers
    jours — jours sans aucune question inclus explicitement à 0 (via
    generate_series), pour que le graphique affiche une série continue
    sans jour manquant qui décalerait visuellement les barres.

    generate_series(...) AS series(day) nomme explicitement l'alias de
    table ("series") séparément de sa colonne ("day") — sans ça,
    Postgres donne le même nom "day" à la table ET à sa colonne, ce qui
    rend toute référence non qualifiée à "day" ambiguë (JOIN, SELECT,
    ORDER BY)."""
    result = await db.execute(
        text("""
            SELECT series.day AS day, COALESCE(counts.total, 0) AS total
            FROM generate_series(
                (now() - ((:days - 1) * INTERVAL '1 day'))::date,
                now()::date,
                INTERVAL '1 day'
            ) AS series(day)
            LEFT JOIN (
                SELECT created_at::date AS day, COUNT(*) AS total
                FROM chat_messages
                WHERE role = 'user' AND created_at >= now() - ((:days - 1) * INTERVAL '1 day')
                GROUP BY created_at::date
            ) counts ON counts.day = series.day
            ORDER BY series.day
        """),
        {"days": days},
    )
    rows = result.mappings().all()
    return [{"date": row["day"].isoformat(), "count": row["total"]} for row in rows]


async def get_summary(db: AsyncSession, period_days: int = 7) -> dict:
    now = datetime.now(timezone.utc)
    since_current = now - timedelta(days=period_days)
    since_previous = since_current - timedelta(days=period_days)

    questions_current = await count_questions(db, since_current)
    questions_previous = await count_questions(db, since_previous, until=since_current)

    users_current = await count_active_users(db, since_current)
    users_previous = await count_active_users(db, since_previous, until=since_current)

    confidence_current = await average_confidence(db, since_current)
    confidence_previous = await average_confidence(db, since_previous, until=since_current)

    # Les documents indexés n'ont pas d'équivalent "période précédente"
    # significatif (c'est un total cumulé, pas une activité datée) —
    # pas de tendance calculée pour ce KPI.
    documents_total = await count_indexed_documents(db)

    return {
        "questions_posees": {
            "value": questions_current,
            "trend_pct": _trend_pct(questions_current, questions_previous),
        },
        "confiance_moyenne": {
            "value": confidence_current or 0.0,
            "trend_pct": (
                round(confidence_current - confidence_previous, 1)
                if confidence_current is not None and confidence_previous is not None
                else None
            ),
        },
        "documents_indexes": {
            "value": documents_total,
            "trend_pct": None,
        },
        "utilisateurs_actifs": {
            "value": users_current,
            "trend_pct": _trend_pct(users_current, users_previous),
        },
        "period_days": period_days,
    }


async def connector_status(db: AsyncSession) -> list[dict]:
    """Une ligne par instance de connecteur (pas d'agrégation par
    source) — reflète exactement ce qui existe en base, y compris si
    plusieurs instances existent pour un même type de source."""
    result = await db.execute(
        text("""
            SELECT source_type, instance_label, is_enabled, last_sync_status, last_sync_at
            FROM connector_configs
            ORDER BY source_type, instance_label
        """)
    )
    rows = result.mappings().all()
    return [
        {
            "source_type": row["source_type"],
            "instance_label": row["instance_label"],
            "is_enabled": row["is_enabled"],
            "last_sync_status": row["last_sync_status"],
            "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
        }
        for row in rows
    ]


async def recent_questions(db: AsyncSession, limit: int = 10) -> list[dict]:
    """Dernières questions posées, TOUS UTILISATEURS CONFONDUS — vue
    admin globale. Ne réutilise volontairement PAS
    app/db/chat_history.py (filtré par user_id, pour le chat personnel
    de chaque compte) : ici on veut au contraire l'activité de toute la
    plateforme, avec le nom de l'utilisateur affiché pour chaque ligne.

    Pour chaque question (role='user'), la réponse associée (role=
    'assistant', juste après dans la même conversation) est retrouvée
    via une sous-requête corrélée — le volume affiché ici (limite
    10-20 lignes) rend ce choix largement suffisant en performance,
    plus simple à lire qu'une jointure complexe ou un second aller-
    retour applicatif."""
    result = await db.execute(
        text("""
            SELECT
                cm.id,
                cm.content,
                cm.created_at,
                u.full_name AS user_full_name,
                (
                    SELECT a.sources
                    FROM chat_messages a
                    WHERE a.conversation_id = cm.conversation_id
                      AND a.role = 'assistant'
                      AND a.created_at >= cm.created_at
                    ORDER BY a.created_at ASC
                    LIMIT 1
                ) AS answer_sources
            FROM chat_messages cm
            JOIN chat_conversations cc ON cc.id = cm.conversation_id
            LEFT JOIN public.users u ON u.id = cc.user_id
            WHERE cm.role = 'user'
            ORDER BY cm.created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = result.mappings().all()

    items = []
    for row in rows:
        sources = row["answer_sources"] or []
        source_types = sorted({s.get("source_type") for s in sources if s.get("source_type")})
        best_score = max((s.get("score") for s in sources if s.get("score") is not None), default=None)
        items.append({
            "id": row["id"],
            "user_full_name": row["user_full_name"] or "Utilisateur inconnu",
            "question": row["content"],
            "source_types": source_types,
            "confidence_pct": round(best_score * 100, 1) if best_score is not None else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })
    return items