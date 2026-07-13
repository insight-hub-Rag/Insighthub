"""
LLM Router — utilisé uniquement quand le Rule Router n'a trouvé aucun
signal clair (retourne None). Envoie la question à un LLM (Groq) qui
retourne un JSON structuré : sources à interroger, type de recherche,
filtres éventuels, score de confiance.

Contrairement au Rule Router, celui-ci comprend l'intention même mal
formulée — au prix d'un appel réseau et d'une latence plus élevée.
"""

import json
import logging

from config import settings
from app.core.models import PreprocessedQuery, RoutingDecision

logger = logging.getLogger(__name__)

# Sources réellement disponibles dans ce projet.
AVAILABLE_SOURCES = ["jira", "confluence", "sharepoint", "sql"]

SYSTEM_PROMPT = f"""Tu es un routeur pour un assistant RAG d'entreprise.
Analyse la question et retourne UNIQUEMENT un JSON valide (rien d'autre,
pas de texte avant/après, pas de markdown) avec ce format exact :

{{
  "sources": [liste parmi {AVAILABLE_SOURCES}],
  "search_type": "semantic" ou "metadata" ou "hybrid",
  "filters": {{}},
  "confidence": nombre entre 0 et 1,
  "reasoning": "explication courte en français"
}}

Règles :
- "sources" : choisis uniquement les sources pertinentes, jamais vide
- "sql" : choisis cette source pour toute question portant sur des
  données structurées/chiffrées de l'entreprise (comptages, moyennes,
  agrégations, RH, projets, tickets en base de données) — PAS pour des
  questions de documentation ou de contenu textuel narratif
- "search_type" : "semantic" si question ouverte, "metadata" si filtre
  exact demandé, "hybrid" si les deux (pour "sql", cette valeur est
  ignorée par l'agent mais garde "hybrid" par défaut)
- "filters" : uniquement si un critère précis est demandé (statut,
  priorité...), sinon objet vide {{}}
- "confidence" : ta certitude sur cette décision de routage
- Si la question ne concerne clairement aucune source d'entreprise,
  mets "confidence" bas (< 0.3)"""


class LLMRouter:

    def route(self, query: PreprocessedQuery) -> RoutingDecision:
        try:
            from groq import Groq
            client = Groq(api_key=settings.groq_api_key)

            response = client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query.cleaned_text},
                ],
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            parsed = json.loads(raw)

            decision = RoutingDecision(
                sources=self._validate_sources(parsed.get("sources", [])),
                search_type=parsed.get("search_type", "hybrid"),
                filters=parsed.get("filters", {}) or {},
                confidence=float(parsed.get("confidence", 0.5)),
                router_used="llm",
                reasoning=parsed.get("reasoning", ""),
            )
            logger.info(f"[LLMRouter] {decision}")
            return decision

        except Exception as e:
            logger.error(f"[LLMRouter] Erreur, fallback sur toutes les sources : {e}")
            return self._fallback_decision()

    @staticmethod
    def _validate_sources(sources: list) -> list[str]:
        """Ne garde que les sources réellement disponibles — au cas où
        le LLM halluciné une source inexistante."""
        valid = [s for s in sources if s in AVAILABLE_SOURCES]
        return valid if valid else AVAILABLE_SOURCES

    @staticmethod
    def _fallback_decision() -> RoutingDecision:
        """En cas d'échec total (API down, JSON invalide...), on cherche
        dans les sources documentaires plutôt que de bloquer le
        pipeline — dégradation gracieuse. "sql" est volontairement
        exclu du fallback : générer une requête SQL sans certitude sur
        l'intention réelle est risqué, mieux vaut chercher dans la
        documentation par défaut."""
        return RoutingDecision(
            sources=["jira", "confluence", "sharepoint"],
            search_type="hybrid",
            filters={},
            confidence=0.3,
            router_used="llm",
            reasoning="Fallback suite à une erreur du LLM Router",
        )