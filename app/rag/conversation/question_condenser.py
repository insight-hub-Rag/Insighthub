import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 4000

SYSTEM_PROMPT = """Tu reformules une question de suivi en question autonome.

Règles :
- Ne réponds jamais à la question.
- N'ajoute aucune information absente de l'historique.
- Préserve exactement les identifiants, noms, statuts et priorités.
- Si la question est déjà autonome, retourne-la sans modification.
- Retourne uniquement la question reformulée, sans préfixe ni markdown."""


class QuestionCondenser:
    """Transforme une question contextuelle en question autonome."""

    def condense(self, question: str, history: list[dict[str, Any]] | None) -> str:
        prepared_history = self._prepare_history(history)
        if not prepared_history:
            return question

        prompt = self._build_prompt(question, prepared_history)
        try:
            if settings.use_bedrock:
                condensed = self._condense_bedrock(prompt)
            else:
                condensed = self._condense_groq(prompt)
            condensed = condensed.strip()
            if not condensed:
                raise ValueError("Le modèle a retourné une question vide")
            logger.info(
                "[QuestionCondenser] Question reformulée : %r -> %r",
                question[:120],
                condensed[:120],
            )
            return condensed
        except Exception as exc:
            logger.warning(
                "[QuestionCondenser] Échec de condensation, question originale conservée : %s",
                exc,
            )
            return question

    @staticmethod
    def _prepare_history(
        history: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        if not history:
            return []

        prepared: list[dict[str, str]] = []
        total_chars = 0
        for item in reversed(history[-MAX_HISTORY_MESSAGES:]):
            role = str(item.get("role", ""))
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue

            remaining = MAX_HISTORY_CHARS - total_chars
            if remaining <= 0:
                break
            content = content[-remaining:]
            prepared.append({"role": role, "content": content})
            total_chars += len(content)

        prepared.reverse()
        return prepared

    @staticmethod
    def _build_prompt(question: str, history: list[dict[str, str]]) -> str:
        lines = [
            f"{item['role'].upper()}: {item['content']}" for item in history
        ]
        return (
            "HISTORIQUE :\n"
            + "\n".join(lines)
            + f"\n\nQUESTION DE SUIVI :\n{question}\n\nQUESTION AUTONOME :"
        )

    @staticmethod
    def _condense_groq(prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=160,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _condense_bedrock(prompt: str) -> str:
        import boto3

        client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        response = client.converse(
            modelId=settings.bedrock_text_model,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 160, "temperature": 0.0},
        )
        return response["output"]["message"]["content"][0]["text"]
