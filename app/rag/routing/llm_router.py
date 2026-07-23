"""
LLM Router — utilisé pour TOUTE question qui n'est pas un identifiant
explicite (le Rule Router ne gère plus que ce cas, cf rule_router.py).
Envoie la question à un LLM (Groq ou AWS Bedrock, selon
settings.use_bedrock — même bascule que Generator) qui retourne un
JSON structuré : sources à interroger, type de recherche, filtres
éventuels, score de confiance, et un jugement explicite de scope
(in_scope).

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
  "in_scope": true ou false,
  "sources": [liste parmi {AVAILABLE_SOURCES}],
  "search_type": "semantic" ou "metadata" ou "hybrid",
  "filters": {{}},
  "confidence": nombre entre 0 et 1,
  "reasoning": "explication courte en français"
}}

Règles :
- "in_scope" : false si la question ne concerne clairement AUCUNE
  donnée d'entreprise (Jira, Confluence, SharePoint, ServiceNow, RH,
  business) — par ex. culture générale, salutations, questions
  personnelles, code générique sans lien avec l'entreprise. true sinon.
  Un mot-clé quantitatif isolé ("combien", "total", "moyenne"...) ne
  suffit PAS à rendre une question "in_scope" : "combien pèse une
  baleine bleue ?" reste hors scope malgré le mot "combien".
  Si "in_scope" est false, "sources" doit être une liste vide et les
  autres champs de recherche n'ont pas d'importance.
- "sources" : choisis uniquement les sources pertinentes, jamais vide
  SI "in_scope" est true
- "sql" : choisis cette source pour toute question portant sur des
  données structurées/chiffrées de l'entreprise (comptages, moyennes,
  agrégations, RH, projets, tickets en base de données) — PAS pour des
  questions de documentation ou de contenu textuel narratif
- ATTENTION AMBIGUÏTÉ CONNUE — "ticket(s)" : ce mot peut désigner deux
  choses différentes selon le contexte :
    1. un vrai ticket Jira (contenu narratif : titre, description,
       commentaires) → source "jira"
    2. une ligne dans la table SQL interne `tickets` (projet, priorité,
       booléen resolved) → source "sql", surtout si la question
       demande un COMPTAGE, une AGRÉGATION ou un FILTRE numérique
       (ex: "combien de tickets non résolus", "tickets par priorité")
  Règle pratique : si la question porte sur COMBIEN/COMPTER/AGRÉGER des
  tickets → "sql". Si elle demande de LIRE/COMPRENDRE le contenu d'un
  ticket précis (texte, description, commentaires) → "jira".
- "search_type" : "semantic" si question ouverte, "metadata" si filtre
  exact demandé, "hybrid" si les deux (pour "sql", cette valeur est
  ignorée par l'agent mais garde "hybrid" par défaut)
- "filters" : uniquement si un critère précis est demandé (statut,
  priorité...), sinon objet vide {{}}. La valeur d'un filtre peut être
  UNE chaîne, OU une LISTE de valeurs candidates si tu n'es pas sûr de
  laquelle existe réellement (ex: "urgent" peut vouloir dire tout en
  haut de l'échelle, sans savoir si c'est "Highest" ou seulement
  "High" dans ce projet précis — dans le doute, propose les deux :
  ["Highest", "High"]). Respecte la casse et les accents des valeurs :
    - "status" (Jira) : "À faire" | "En cours" | "Terminé"
      (l'instance Jira de ce projet est en français, PAS en anglais —
      ne traduis jamais ces valeurs en "To Do"/"In Progress"/"Done")
    - "priority" (Jira) : "Highest" | "High" | "Medium" | "Low" | "Lowest"
      (la priorité, elle, reste en anglais — ne pas traduire non plus)
  Exemples : "en cours"/"en traitement" -> "En cours" ; "à faire"/"pas
  commencé" -> "À faire" ; "terminé"/"fini"/"fait" -> "Terminé" ;
  "urgent"/"critique" -> ["Highest", "High"] (les deux niveaux hauts,
  incertitude sur lequel existe) ; "mineur"/"pas urgent" -> ["Low", "Lowest"]
  ; ATTENTION au sens positif vs négatif, ne les confonds JAMAIS :
    - "résolu"/"résolus" (POSITIF, sans négation) -> "status": "Terminé"
    - "non résolu"/"pas résolu"/"irrésolu" (NÉGATIF) -> "status_not": "Terminé"
      (jamais une énumération manuelle du complémentaire, utilise
      TOUJOURS "status_not" pour "pas X" / "non X" / "sauf X")
- "confidence" : ta certitude sur cette décision de routage

Exemples :
Q: "combien de tickets non résolus a le projet InsightHub ?"
{{"in_scope": true, "sources": ["sql"], "search_type": "hybrid", "filters": {{}}, "confidence": 0.9, "reasoning": "Comptage sur la table SQL tickets"}}

Q: "montre-moi les tickets urgents et leur description"
{{"in_scope": true, "sources": ["jira"], "search_type": "hybrid", "filters": {{"priority": "Highest"}}, "confidence": 0.85, "reasoning": "Lecture du contenu de tickets Jira, pas un comptage"}}

Q: "combien pèse une baleine bleue ?"
{{"in_scope": false, "sources": [], "search_type": "hybrid", "filters": {{}}, "confidence": 0.95, "reasoning": "Question de culture générale, aucun lien avec les données d'entreprise"}}"""


class LLMRouter:

    def route(self, query: PreprocessedQuery) -> RoutingDecision:
        if settings.use_bedrock:
            return self._route_bedrock(query)
        return self._route_groq(query)

    def _route_groq(self, query: PreprocessedQuery) -> RoutingDecision:
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
                max_tokens=300,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            decision = self._parse_response(raw)
            logger.info(f"[LLMRouter][Groq] {decision}")
            return decision

        except Exception as e:
            logger.error(f"[LLMRouter][Groq] Erreur, fallback : {e}")
            return self._fallback_decision()

    def _route_bedrock(self, query: PreprocessedQuery) -> RoutingDecision:
        try:
            import boto3
            client = boto3.client(
                "bedrock-runtime",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            # Pas de mode JSON strict côté Bedrock Converse (contrairement
            # à response_format={"type": "json_object"} chez Groq) — le
            # prompt système impose déjà "UNIQUEMENT un JSON valide", et
            # _parse_response() nettoie les éventuelles fences markdown
            # en filet de sécurité si le modèle en ajoute quand même.
            response = client.converse(
                modelId=settings.bedrock_text_model,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[
                    {"role": "user", "content": [{"text": query.cleaned_text}]}
                ],
                inferenceConfig={"maxTokens": 300, "temperature": 0.0},
            )
            raw = response["output"]["message"]["content"][0]["text"]
            decision = self._parse_response(raw)
            logger.info(f"[LLMRouter][Bedrock] {decision}")
            return decision

        except Exception as e:
            logger.error(f"[LLMRouter][Bedrock] Erreur, fallback : {e}")
            return self._fallback_decision()

    def _parse_response(self, raw: str) -> RoutingDecision:
        """Parse le JSON retourné par le LLM (Groq ou Bedrock). Nettoie
        d'éventuelles fences markdown ```json ... ``` que Bedrock (sans
        mode JSON strict) peut ajouter malgré la consigne du prompt."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()

        parsed = json.loads(cleaned)
        in_scope = bool(parsed.get("in_scope", True))

        return RoutingDecision(
            # Hors scope -> sources vides : inutile de retomber sur
            # AVAILABLE_SOURCES par défaut, l'orchestrateur ne va de
            # toute façon pas lancer les agents dans ce cas.
            sources=self._validate_sources(parsed.get("sources", []))
            if in_scope else [],
            search_type=parsed.get("search_type", "hybrid"),
            filters=parsed.get("filters", {}) or {},
            confidence=float(parsed.get("confidence", 0.5)),
            router_used="llm",
            reasoning=parsed.get("reasoning", ""),
            in_scope=in_scope,
        )

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
        documentation par défaut. in_scope=True par défaut (dataclass) :
        en cas d'erreur technique, on préfère tenter une recherche
        plutôt que de rejeter à tort une question légitime."""
        return RoutingDecision(
            sources=["jira", "confluence", "sharepoint"],
            search_type="hybrid",
            filters={},
            confidence=0.3,
            router_used="llm",
            reasoning="Fallback suite à une erreur du LLM Router",
        )