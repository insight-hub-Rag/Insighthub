"""
Assigne les conversations de chat sans propriétaire (user_id NULL —
créées avant l'introduction de l'authentification) à un compte donné,
identifié par email.

Usage :
    python -m scripts.assign_orphan_conversations <email>

Exemple :
    python -m scripts.assign_orphan_conversations imane@insighthub.ma

Idempotent : relancer après coup ne fait rien (plus aucune conversation
n'a user_id NULL), le script te le confirme plutôt que d'échouer.
"""

import asyncio
import sys

from sqlalchemy import text

from app.db.database import AsyncSessionLocal


async def assign_orphan_conversations(email: str) -> None:
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            text("SELECT id, full_name FROM public.users WHERE email = :email"),
            {"email": email},
        )
        user = user_result.mappings().first()
        if user is None:
            print(f"Aucun compte trouvé pour {email} — vérifie l'adresse.")
            return

        update_result = await session.execute(
            text("""
                UPDATE chat_conversations
                SET user_id = :user_id
                WHERE user_id IS NULL
            """),
            {"user_id": user["id"]},
        )
        await session.commit()

        count = update_result.rowcount
        if count == 0:
            print("Aucune conversation orpheline à assigner — déjà fait, ou base vide.")
        else:
            print(f"{count} conversation(s) assignée(s) à {user['full_name']} ({email}).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.assign_orphan_conversations <email>")
        sys.exit(1)

    asyncio.run(assign_orphan_conversations(sys.argv[1]))