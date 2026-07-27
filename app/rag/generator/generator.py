"""
Generator — dernière étape du pipeline. Reçoit les chunks déjà
rerankés (ou passés tels quels si le reranking a été sauté pour un
match exact par ID), les fait passer par le Context Builder (budget de
tokens), construit le prompt, et appelle le LLM (Groq en dev, Bedrock
en prod).
"""

import logging
import time

from config import settings
from app.core.models import RetrievedChunk, RAGResponse
from app.rag.generator.prompt_builder import build_prompt
from app.rag.generator.context_builder import build_context

logger = logging.getLogger(__name__)


def _ensure_all_sources_mentioned(answer: str, chunks: list[RetrievedChunk]) -> str:
    """
    Vérifie que chaque chunk pertinent (identifié par son document_id,
    ex: "IH-1") apparaît quelque part dans le texte généré. Si le LLM
    en a omis un — un petit modèle peut mal compter sur une liste de
    plusieurs éléments — on le rajoute explicitement en fin de réponse
    plutôt que de laisser une omission silencieuse.

    Heuristique volontairement simple (présence de la sous-chaîne
    document_id) : suffisant pour des identifiants distinctifs comme
    "IH-1", pas une vérification sémantique complète — mais c'est un
    filet de sécurité, pas le mécanisme principal de qualité.
    """
    missing = []
    seen_document_ids = set()
    for c in chunks:
        if not c.document_id or c.document_id in answer:
            continue
        if c.document_id in seen_document_ids:
            # Même document déjà ajouté via un autre chunk (ex: 2
            # passages du même document Confluence) — ne pas dupliquer.
            continue
        seen_document_ids.add(c.document_id)
        missing.append(c)
    if not missing:
        return answer

    extra_lines = "\n".join(
        f"- {_source_label_for_completion(c)}" for c in missing
    )
    return f"{answer}\n\nÉgalement trouvé(s) :\n{extra_lines}"


def _source_label_for_completion(chunk: RetrievedChunk) -> str:
    if chunk.title and chunk.title.startswith(f"[{chunk.document_id}]"):
        # Le titre contient déjà l'ID en préfixe (ex: transformer Jira
        # qui produit "[IH-1] API Gateway timeout...") — ne pas le
        # répéter une deuxième fois.
        return chunk.title
    if chunk.title:
        return f"[{chunk.document_id}] {chunk.title}"
    return f"[{chunk.document_id}]"


OUT_OF_SCOPE_SYSTEM_PROMPT = """Tu es InsightHub, un assistant interne
d'entreprise (Jira, Confluence, SharePoint, ServiceNow, données RH).

La question posée sort de ce périmètre. Réponds en une phrase, en
français, de façon polie : explique que tu es un assistant dédié aux
données de l'entreprise et que tu ne peux pas répondre à ce type de
question. Ne tente pas d'y répondre avec tes connaissances générales."""


class Generator:

    def generate_out_of_scope(self, question: str) -> RAGResponse:
        """Réponse directe pour une question hors périmètre entreprise —
        appelée par l'orchestrateur avant même de lancer les agents.
        Pas de contexte RAG donc pas de source : sources=[] est correct
        ici (contrairement à une réponse RAG normale, où on doit
        toujours pouvoir citer au moins une source)."""
        messages = [
            {"role": "system", "content": OUT_OF_SCOPE_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        if settings.use_bedrock and settings.aws_access_key_id:
            answer, model = self._generate_bedrock(messages)
        else:
            answer, model = self._generate_groq(messages)

        logger.info("[Generator] Réponse hors-scope générée directement")

        return RAGResponse(
            question=question,
            answer=answer,
            sources=[],
            model=model,
            total_chunks_searched=0,
        )

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        max_context_tokens: int = 2000,
        filters_were_requested: bool = False,
    ) -> RAGResponse:
        """
        `filters_were_requested` : True si le routeur a extrait un
        filtre exact (status, priority...) pour cette question — dans
        ce cas, TOUT chunk qui arrive jusqu'ici a déjà passé le
        filtrage strict (cf base_agent._matches_filters), donc en
        omettre un dans le texte est un vrai oubli du modèle, à
        compléter automatiquement (_ensure_all_sources_mentioned).

        Si False (recherche sémantique ouverte, aucun filtre demandé),
        le modèle peut légitimement choisir de ne mentionner qu'une
        partie des chunks (ex: "lesquels sont urgents ?" sans filtre
        explicite — le modèle raisonne lui-même sur le contenu) : dans
        ce cas on NE complète PAS, pour ne pas rajouter des éléments
        que le modèle a délibérément écartés à raison.
        """
        if not chunks:
            return RAGResponse(
                question=question,
                answer="Je n'ai pas trouvé d'informations pertinentes.",
                sources=[],
                model="none",
                total_chunks_searched=0,
            )

        context_chunks = build_context(chunks, max_tokens=max_context_tokens)
        messages = build_prompt(question, context_chunks)

        t0 = time.time()
        if settings.use_bedrock and settings.aws_access_key_id:
            logger.info("[Generator] Utilisation AWS Bedrock")
            answer, model = self._generate_bedrock(messages)
        else:
            logger.info("[Generator] Utilisation Groq")
            answer, model = self._generate_groq(messages)
        t_llm = time.time() - t0

        logger.info(f"[Generator] LLM={t_llm*1000:.1f}ms | model={model}")

        # Garde-fou déterministe : un petit modèle (Nova Micro) peut
        # correctement identifier TOUS les chunks pertinents dans les
        # `sources` structurées, mais en "oublier" un dans le texte
        # libre de la réponse (vécu en pratique : 4 tickets trouvés,
        # seulement 3 mentionnés en prose). Plutôt que d'espérer une
        # énumération parfaite à chaque appel, on vérifie nous-mêmes et
        # on complète — jamais d'omission silencieuse côté utilisateur.
        if filters_were_requested:
            answer = _ensure_all_sources_mentioned(answer, context_chunks)

        sources = self._build_sources(context_chunks)

        return RAGResponse(
            question=question,
            answer=answer,
            sources=sources,
            model=model,
            total_chunks_searched=len(chunks),
        )

    @staticmethod
    def _build_sources(chunks: list[RetrievedChunk]) -> list[dict]:
        """
        Construit la liste `sources` de la réponse, avec un `score`
        toujours interprétable comme un pourcentage (0 à 1, affiché
        ensuite ×100 côté frontend).

        Cas particulier : `rerank_score` (cross-encoder) est un logit
        BRUT, non borné (souvent négatif, ex: -7.57 même pour le
        meilleur résultat) — ce n'est PAS une probabilité. L'afficher
        tel quel donnait des pourcentages absurdes ("-757%"). On le
        normalise ici en min-max sur les chunks de CETTE réponse
        (le moins bon des chunks affichés -> 0%, le meilleur -> 100%)
        — un classement relatif honnête, pas une fausse précision
        absolue que le score brut ne permet pas de toute façon.

        Les autres types de score (sql_score, vector_score...) sont
        déjà dans une échelle raisonnable, on les garde tels quels.
        """
        rerank_values = [c.rerank_score for c in chunks if c.rerank_score is not None]
        rerank_min = min(rerank_values) if rerank_values else 0.0
        rerank_max = max(rerank_values) if rerank_values else 1.0
        rerank_span = (rerank_max - rerank_min) or 1.0  # évite une division par zéro

        sources = []
        for c in chunks:
            if c.rerank_score is not None:
                score = (c.rerank_score - rerank_min) / rerank_span
            else:
                score = Generator._best_score(c)

            sources.append({
                "chunk_id": c.chunk_id,
                "source_type": c.source_type,
                "document_id": c.document_id,
                "title": c.title,
                "score": round(score, 4),
            })
        return sources

    @staticmethod
    def _best_score(chunk: RetrievedChunk) -> float:
        """Affiche le score le plus significatif disponible. sql_score
        passe avant rrf_score : un match exact (1.0) est plus parlant
        pour l'utilisateur qu'un score de fusion RRF générique."""
        for score in (chunk.rerank_score, chunk.sql_score,
                      chunk.vector_score, chunk.bm25_score, chunk.rrf_score):
            if score is not None:
                return round(score, 4)
        return 0.0

    def _generate_groq(self, messages: list[dict]) -> tuple[str, str]:
        try:
            from groq import Groq
            client = Groq(api_key=settings.groq_api_key)
            response = client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=0.1,
                max_tokens=300,
            )
            answer = response.choices[0].message.content
            logger.info(f"[Generator] Groq OK | model={settings.groq_model}")
            return answer, settings.groq_model
        except Exception as e:
            logger.error(f"[Generator] Erreur Groq : {e}")
            return f"Erreur : {str(e)}", "error"

    def _generate_bedrock(self, messages: list[dict]) -> tuple[str, str]:
        try:
            import boto3
            client = boto3.client(
                "bedrock-runtime",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            response = client.converse(
                modelId="us.amazon.nova-micro-v1:0",
                system=[{"text": messages[0]["content"]}],
                messages=[
                    {"role": "user", "content": [{"text": messages[1]["content"]}]}
                ],
                inferenceConfig={"maxTokens": 300, "temperature": 0.1},
            )
            answer = response["output"]["message"]["content"][0]["text"]
            logger.info("[Generator] Bedrock Nova Micro OK")
            return answer, "bedrock-nova-micro"
        except Exception as e:
            logger.error(f"[Generator] Erreur Bedrock : {e} — Fallback Groq")
            return self._generate_groq(messages)