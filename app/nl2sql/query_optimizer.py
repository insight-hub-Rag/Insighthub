"""
app/nl2sql/query_optimizer.py

Génère une suggestion d'amélioration en langage naturel pour une
requête SQL problématique (lente, tronquée, ou en échec).

N'est appelé QUE dans les cas qui le justifient (décision prise par
orchestrator.py) : pas d'appel LLM systématique à chaque question
rapide et réussie, pour ne pas ajouter de coût/latence inutile.

Deux modes de suggestion :
- Heuristique (rapide, gratuit) : couvre les cas fréquents identifiables
  par motif simple (SELECT * sans LIMIT, absence de clause WHERE sur
  une grosse table...).
- LLM (fallback) : pour les cas plus subtils, notamment les échecs
  d'exécution (timeout, erreur SQL) où une réécriture intelligente est
  nécessaire — cf. l'exemple Oracle de la maquette ("Rewrite the
  aggregation explicitly...").
"""

import logging
import re

import boto3

logger = logging.getLogger(__name__)

_SELECT_STAR_PATTERN = re.compile(r"select\s+\*", re.IGNORECASE)
_LIMIT_PATTERN = re.compile(r"\blimit\b", re.IGNORECASE)


class QueryOptimizer:

    def __init__(self, bedrock_model_id: str, aws_region: str):
        self._model_id = bedrock_model_id
        self._client = boto3.client("bedrock-runtime", region_name=aws_region)

    async def suggest(
        self,
        sql: str,
        exec_time_ms: float | None,
        truncated: bool,
        error_message: str | None,
    ) -> str | None:
        """Retourne une suggestion textuelle courte, ou None si rien
        à signaler (cas normal, ne devrait pas être appelé dans ce cas
        mais reste défensif)."""

        heuristic = self._try_heuristic(sql, truncated)
        if heuristic:
            return heuristic

        if error_message:
            return await self._suggest_via_llm(
                sql, reason=f"Cette requête a échoué : {error_message}"
            )

        if exec_time_ms is not None:
            return await self._suggest_via_llm(
                sql, reason=f"Cette requête a mis {exec_time_ms:.0f}ms à s'exécuter, "
                            f"ce qui est lent."
            )

        return None

    def _try_heuristic(self, sql: str, truncated: bool) -> str | None:
        """Cas fréquents détectables sans appel LLM — rapide et gratuit."""
        has_select_star = bool(_SELECT_STAR_PATTERN.search(sql))
        has_limit = bool(_LIMIT_PATTERN.search(sql))

        if truncated and not has_limit:
            return (
                "Ajoutez une clause LIMIT pour réduire le nombre de lignes "
                "retournées et accélérer l'exécution."
            )
        if has_select_star:
            return (
                "Remplacez SELECT * par les colonnes explicitement nécessaires "
                "pour réduire le volume de données transférées."
            )
        return None

    async def _suggest_via_llm(self, sql: str, reason: str) -> str:
        prompt = f"""Cette requête SQL pose un problème :

{sql}

{reason}

En UNE phrase courte et concrète (moins de 25 mots), suggère une
amélioration précise. Réponds uniquement avec la suggestion, sans
préambule ni explication supplémentaire."""

        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 100, "temperature": 0.0},
            )
            suggestion = response["output"]["message"]["content"][0]["text"].strip()
            logger.info(f"[QueryOptimizer] Suggestion LLM générée : {suggestion}")
            return suggestion
        except Exception as exc:
            logger.error(f"[QueryOptimizer] Échec génération suggestion : {exc}")
            return "Optimisation recommandée — requête lente ou en échec."