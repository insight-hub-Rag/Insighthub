"""
Crée (ou vérifie l'existence d') un compte utilisateur InsightHub, avec
le rôle de ton choix — version généralisée de create_admin.py.

Usage :
    python -m scripts.create_user <email> <mot_de_passe> "<nom complet>" <role>

Rôles acceptés : admin, rh, user (colonne libre en base, mais ce sont
les 3 valeurs actuellement gérées côté frontend — voir RoleContext.tsx).

Exemples :
    python -m scripts.create_user salma@insighthub.ma MotDePasseRH123 "Salma L." rh
    python -m scripts.create_user karim@insighthub.ma MotDePasseUser123 "Karim B." user

Idempotent : relancer avec le même email ne crée pas de doublon
(ON CONFLICT DO NOTHING) — le script te dit alors que le compte existe
déjà plutôt que d'échouer silencieusement.
"""

import asyncio
import sys

from sqlalchemy import text

from app.auth.security import hash_password
from app.db.database import AsyncSessionLocal

VALID_ROLES = {"admin", "rh", "user"}


async def create_user(email: str, password: str, full_name: str, role: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                INSERT INTO public.users (email, hashed_password, full_name, role)
                VALUES (:email, :hashed_password, :full_name, :role)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """),
            {
                "email": email,
                "hashed_password": hash_password(password),
                "full_name": full_name,
                "role": role,
            },
        )
        created_id = result.scalar_one_or_none()
        await session.commit()

        if created_id is None:
            print(f"Un compte existe déjà pour {email} — aucune modification effectuée.")
            return

        print(f"Compte créé avec succès : {email} (rôle: {role}, id: {created_id})")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print('Usage: python -m scripts.create_user <email> <mot_de_passe> "<nom complet>" <role>')
        print(f"Rôles actuellement gérés côté frontend : {', '.join(sorted(VALID_ROLES))}")
        sys.exit(1)

    _, email_arg, password_arg, full_name_arg, role_arg = sys.argv

    if role_arg not in VALID_ROLES:
        print(f"Attention : '{role_arg}' n'est pas un rôle géré par le frontend actuel "
              f"({', '.join(sorted(VALID_ROLES))}) — le compte sera créé quand même, "
              f"mais aucun menu ne lui correspondra dans la sidebar tant que "
              f"RoleContext.tsx n'est pas mis à jour.")

    asyncio.run(create_user(email_arg, password_arg, full_name_arg, role_arg))