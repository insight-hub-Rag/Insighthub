"""
app/nl2sql/query_validator.py

Validation READ-ONLY stricte de la requête SQL générée par le LLM,
avant toute exécution contre la base cible.

Logique volontairement pure (aucun accès DB, aucun appel LLM) — c'est
la brique la plus critique du module côté sécurité, donc elle doit
rester isolée et testable unitairement sans dépendance externe.

Approche : liste blanche (whitelist), pas liste noire. On autorise
UNIQUEMENT les instructions commençant par SELECT ou WITH (CTE en
lecture), et on bloque explicitement tout mot-clé de mutation, même
imbriqué dans une sous-requête ou après un point-virgule.
"""

import re

from app.nl2sql.models import ValidationResult

# Mots-clés strictement interdits, quelle que soit leur position dans
# la requête (y compris dans une sous-requête ou une CTE). Recherche
# insensible à la casse, sur mot entier (évite les faux positifs du
# type colonne "updated_at" contenant "update").
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "MERGE", "REPLACE", "EXEC",
    "EXECUTE", "CALL", "COPY", "VACUUM", "REINDEX", "ATTACH",
    "DETACH", "PRAGMA",
]

# Seules ces instructions de tête sont autorisées.
# WITH couvre les CTE en lecture (WITH ... AS (SELECT ...) SELECT ...).
ALLOWED_LEADING_KEYWORDS = ("SELECT", "WITH")

_FORBIDDEN_PATTERN = re.compile(
    r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Commentaires SQL pouvant cacher une instruction ou neutraliser
# un contrôle naïf (ex: "SELECT 1; --DROP TABLE x").
_COMMENT_PATTERN = re.compile(r"(--.*$)|(/\*.*?\*/)", re.MULTILINE | re.DOTALL)


class QueryValidator:

    def validate(self, sql: str) -> ValidationResult:
        if not sql or not sql.strip():
            return ValidationResult(is_valid=False, reason="Requête vide.")

        cleaned = self._strip_comments(sql).strip()

        # Une seule instruction autorisée : on tolère UN point-virgule
        # final optionnel, mais rien après.
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        if len(statements) != 1:
            return ValidationResult(
                is_valid=False,
                reason="Une seule instruction SQL est autorisée par requête.",
            )

        statement = statements[0]

        # Vérifie le mot-clé de tête
        leading_word = statement.split(None, 1)[0].upper() if statement.split() else ""
        if leading_word not in ALLOWED_LEADING_KEYWORDS:
            return ValidationResult(
                is_valid=False,
                reason=f"Instruction non autorisée : doit commencer par "
                       f"{' ou '.join(ALLOWED_LEADING_KEYWORDS)}, reçu '{leading_word}'.",
            )

        # Vérifie l'absence de mots-clés de mutation, même en sous-requête
        forbidden_match = _FORBIDDEN_PATTERN.search(statement)
        if forbidden_match:
            return ValidationResult(
                is_valid=False,
                reason=f"Mot-clé interdit détecté : '{forbidden_match.group(1).upper()}'.",
            )

        return ValidationResult(is_valid=True)

    @staticmethod
    def _strip_comments(sql: str) -> str:
        """Retire les commentaires SQL avant analyse, pour empêcher
        qu'une instruction interdite y soit dissimulée ou qu'un
        commentaire ne neutralise le point-virgule de fin."""
        return _COMMENT_PATTERN.sub(" ", sql)