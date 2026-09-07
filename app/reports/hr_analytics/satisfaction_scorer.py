"""
Satisfaction Scorer — appel LLM (Bedrock) pour scorer un ticket fermé.

Responsabilité UNIQUE : construire le prompt, appeler le LLM, parser
la réponse JSON en TicketScoreOut. Ne touche jamais à la base de
données (ça, c'est repository.py) et ne décide jamais QUAND scorer
(ça, c'est le job séparé — option B).

Réutilise le pattern déjà en place dans app/nl2sql et app/rag/generator
pour l'appel Bedrock (client boto3, converse API).
"""

import json
import logging

from config import settings
from app.reports.hr_analytics.models import TicketScoreOut

logger = logging.getLogger(__name__)

# Incrémenter cette version à chaque changement du prompt — permet de
# savoir quels scores ont été calculés avec quelle version (utile pour
# décider de rescorer après une amélioration du prompt).
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """Tu es un évaluateur interne pour un service support
(Jira / ServiceNow). Tu analyses un ticket fermé et tu dois estimer :

- complexity_score : complexité du ticket (0.0 = trivial, 1.0 = très complexe),
  en te basant sur la description et le nombre d'échanges/commentaires
- satisfaction_score : satisfaction estimée de l'utilisateur/client
  (0.0 = très insatisfait, 1.0 = très satisfait), en te basant sur le
  ton des commentaires, si la résolution semble avoir réellement
  répondu au problème, et le temps de traitement si mentionné
- reasoning : une phrase courte en français justifiant ces deux scores

Réponds UNIQUEMENT avec un objet JSON valide, rien d'autre, sous cette
forme exacte :
{"complexity_score": 0.0, "satisfaction_score": 0.0, "reasoning": "..."}

Ne mets aucun texte avant ou après le JSON. N'invente rien qui n'est
pas dans le contenu fourni."""


class SatisfactionScorer:

    def score_ticket(
        self,
        ticket_id: str,
        source_type: str,
        title: str,
        content: str,
        is_closed: bool,
        resolution_hours: float | None,
    ) -> TicketScoreOut:
        """Appelle le LLM et retourne un score structuré. En cas
        d'erreur (LLM injoignable, JSON invalide), retourne un score
        neutre plutôt que de lever une exception — un ticket non
        scorable ne doit pas bloquer les autres dans le job batch."""
        user_message = (
            f"Ticket [{ticket_id}] — {title}\n\n{content[:3000]}"
        )
        raw_answer = self._call_bedrock(user_message)
        parsed = self._parse_response(raw_answer, ticket_id)

        return TicketScoreOut(
            ticket_id=ticket_id,
            source_type=source_type,
            is_closed=is_closed,
            resolution_hours=resolution_hours,
            complexity_score=parsed["complexity_score"],
            satisfaction_score=parsed["satisfaction_score"],
            llm_reasoning=parsed["reasoning"],
            prompt_version=PROMPT_VERSION,
        )

    def _call_bedrock(self, user_message: str) -> str:
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
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.1},
        )
        return response["output"]["message"]["content"][0]["text"]

    @staticmethod
    def _parse_response(raw_answer: str, ticket_id: str) -> dict:
        try:
            data = json.loads(raw_answer.strip())
            return {
                "complexity_score": float(data["complexity_score"]),
                "satisfaction_score": float(data["satisfaction_score"]),
                "reasoning": str(data.get("reasoning", "")),
            }
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error(
                f"[SatisfactionScorer] Réponse LLM invalide pour {ticket_id} : "
                f"{e} — réponse brute : {raw_answer[:200]}"
            )
            return {
                "complexity_score": 0.5,
                "satisfaction_score": 0.5,
                "reasoning": "Score par défaut — échec du parsing de la réponse LLM.",
            }