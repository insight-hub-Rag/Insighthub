"""
AI Synthesis — génère le texte de synthèse du dashboard ("Synthèse IA").

Responsabilité UNIQUE : un appel LLM léger sur des KPIs déjà agrégés
(pas de logique d'agrégation ici, pas d'accès DB). Généré à la volée à
chaque GET car un seul appel, à coût constant quel que soit le nombre
de tickets — contrairement au scoring par ticket (satisfaction_scorer.py),
qui lui doit être pré-calculé.
"""

import logging

from config import settings
from app.reports.hr_analytics.models import KpiSummaryOut

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un analyste RH interne. On te donne des
indicateurs déjà calculés sur une période. Rédige une synthèse courte
en français (3-4 phrases maximum) :
- Un constat général sur la productivité
- Une remarque sur le taux de résolution et la satisfaction
- Une recommandation courte si pertinent

Ne réponds qu'avec le texte de synthèse, sans titre ni introduction."""


class AiSynthesisGenerator:

    def generate(self, kpis: KpiSummaryOut, best_employee_name: str | None) -> str:
        user_message = (
            f"Tickets traités : {kpis.tickets_traites}\n"
            f"Tickets résolus : {kpis.tickets_resolus}\n"
            f"Temps moyen de résolution : {kpis.temps_moyen_heures or 'N/A'} h\n"
            f"Satisfaction moyenne : {kpis.satisfaction_moyenne or 'N/A'}\n"
            f"Meilleur collaborateur : {best_employee_name or 'N/A'}"
        )
        try:
            return self._call_bedrock(user_message)
        except Exception as e:
            logger.error(f"[AiSynthesis] Échec génération : {e}")
            return "Synthèse indisponible pour le moment."

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
            inferenceConfig={"maxTokens": 200, "temperature": 0.3},
        )
        return response["output"]["message"]["content"][0]["text"]