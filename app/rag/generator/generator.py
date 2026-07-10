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


class Generator:

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        max_context_tokens: int = 2000,
    ) -> RAGResponse:
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

        sources = [
            {
                "chunk_id": c.chunk_id,
                "source_type": c.source_type,
                "document_id": c.document_id,
                "title": c.title,
                "score": self._best_score(c),
            }
            for c in context_chunks
        ]

        return RAGResponse(
            question=question,
            answer=answer,
            sources=sources,
            model=model,
            total_chunks_searched=len(chunks),
        )

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