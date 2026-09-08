"""
Crée (ou vérifie l'existence d') un compte administrateur InsightHub.

Usage :
    python -m scripts.create_admin <email> <mot_de_passe> "<nom complet>"

Exemple :
    python -m scripts.create_admin admin@insighthub.ma MonMotDePasse123 "Admin InsightHub"

Idempotent : relancer avec le même email ne crée pas de doublon
(ON CONFLICT DO NOTHING) — le script te dit alors que le compte existe
déjà plutôt que d'échouer silencieusement.
"""

import asyncio
import sys

from sqlalchemy import text

from app.auth.security import hash_password
from app.db.database import AsyncSessionLocal


async def create_admin(email: str, password: str, full_name: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                INSERT INTO public.users (email, hashed_password, full_name, role)
                VALUES (:email, :hashed_password, :full_name, 'admin')
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """),
            {
                "email": email,
                "hashed_password": hash_password(password),
                "full_name": full_name,
            },
        )
        created_id = result.scalar_one_or_none()
        await session.commit()

        if created_id is None:
            print(f"Un compte existe déjà pour {email} — aucune modification effectuée.")
            return

        print(f"Compte administrateur créé avec succès : {email} (id: {created_id})")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print('Usage: python -m scripts.create_admin <email> <mot_de_passe> "<nom complet>"')
        sys.exit(1)

    _, email_arg, password_arg, full_name_arg = sys.argv
    asyncio.run(create_admin(email_arg, password_arg, full_name_arg))