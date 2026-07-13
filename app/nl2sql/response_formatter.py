"""
app/nl2sql/response_formatter.py

Reformule le résultat brut d'une exécution SQL (lignes/colonnes) en
réponse en langage naturel, compréhensible par l'utilisateur final —
c'est cette réponse qui sera injectée dans RetrievedChunk.content

Ne reformule QUE les résultats en succès — les cas d'échec sont
gérés directement par orchestrator.py avec un message d'erreur clair,
sans appel LLM inutile (cohérent avec query_optimizer.py : pas d'appel
LLM systématique quand une réponse déterministe suffit).
"""

import logging

import boto3

from app.nl2sql.query_executor import ExecutionOutcome

logger = logging.getLogger(__name__)

# Au-delà de ce nombre de lignes, on ne les injecte plus telles quelles
# dans le prompt de reformulation — trop coûteux en tokens pour peu de
# valeur ajoutée. On donne alors un résumé statistique simple au LLM.
MAX_ROWS_IN_PROMPT = 30


class ResponseFormatter:

    def __init__(self, bedrock_model_id: str, aws_region: str):
        self._model_id = bedrock_model_id
        self._client = boto3.client("bedrock-runtime", region_name=aws_region)

    async def format(self, question: str, outcome: ExecutionOutcome) -> str:
        if not outcome.success:
            # Pas d'appel LLM pour un échec — réponse déterministe,
            # claire, sans faux espoir de reformulation "intelligente".
            return (
                "Je n'ai pas pu récupérer cette information : la requête "
                "générée a échoué. Réessayez en reformulant votre question."
            )

        if outcome.row_count == 0:
            return "Aucune donnée ne correspond à votre question."

        prompt = self._build_prompt(question, outcome)

        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 400, "temperature": 0.3},
            )
            answer = response["output"]["message"]["content"][0]["text"].strip()
            logger.info(f"[ResponseFormatter] Réponse générée ({len(answer)} car.)")
            return answer
        except Exception as exc:
            logger.error(f"[ResponseFormatter] Échec reformulation : {exc}")
            return self._fallback_raw_summary(outcome)

    def _build_prompt(self, question: str, outcome: ExecutionOutcome) -> str:
        rows_preview = outcome.rows[:MAX_ROWS_IN_PROMPT]
        rows_text = "\n".join(str(row) for row in rows_preview)

        truncation_note = ""
        if outcome.row_count > MAX_ROWS_IN_PROMPT or outcome.truncated:
            truncation_note = (
                f"\n(Note : {outcome.row_count} résultat(s) au total, "
                f"seuls les {len(rows_preview)} premiers sont montrés ci-dessus.)"
            )

        return f"""Voici le résultat d'une requête sur une base de données
d'entreprise, en réponse à la question posée.

QUESTION : {question}

RÉSULTAT BRUT :
{rows_text}{truncation_note}

Reformule ce résultat en une réponse claire et naturelle en français,
comme si tu répondais directement à la question. Ne mentionne pas la
requête SQL. Reste concis (2-4 phrases). Si le résultat contient des
chiffres, mets-les en avant clairement."""

    @staticmethod
    def _fallback_raw_summary(outcome: ExecutionOutcome) -> str:
        """Filet de sécurité si l'appel LLM de reformulation échoue —
        évite de perdre le résultat déjà obtenu, même sans reformulation
        élégante."""
        return (
            f"{outcome.row_count} résultat(s) trouvé(s) : "
            f"{outcome.rows[:5]}"
            + ("..." if outcome.row_count > 5 else "")
        )