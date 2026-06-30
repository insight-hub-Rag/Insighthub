"""
Embedder : transforme du texte en vecteurs.

Deux stratégies disponibles, choisies via `settings.embedding_provider` :
  - "local"   : sentence-transformers, modèle exécuté localement (par défaut)
  - "bedrock" : AWS Bedrock (Titan Embed), nécessite des credentials AWS

L'Embedder est injecté dans le pipeline (Dependency Injection) plutôt que
d'être un singleton de module — ça le rend testable (on peut injecter un
faux embedder dans les tests) et explicite sur son cycle de vie.
"""

import json
from typing import Optional, Protocol

from loguru import logger

from config import settings
from app.core.models import Chunk


class EmbeddingBackend(Protocol):
    """Contrat minimal que toute stratégie d'embedding doit respecter."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class LocalEmbeddingBackend:
    """Stratégie d'embedding locale, via sentence-transformers."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        logger.info(f"[Embedder] Chargement du modèle local : {model_name}")
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]


class BedrockEmbeddingBackend:
    """Stratégie d'embedding via AWS Bedrock (Titan Embed)."""

    def __init__(self, model_id: str, region: str, access_key: str, secret_key: str):
        import boto3

        if not access_key or not secret_key:
            raise RuntimeError(
                "AWS credentials manquants : aws_access_key_id et "
                "aws_secret_access_key doivent être configurés pour utiliser Bedrock."
            )

        self._model_id = model_id
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        # L'API Bedrock Titan Embed ne supporte qu'un texte à la fois.
        vectors = []
        for text in texts:
            body = json.dumps({"inputText": text[:8000]})
            resp = self._client.invoke_model(
                modelId=self._model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            vectors.append(json.loads(resp["body"].read())["embedding"])
        return vectors


def _build_backend() -> EmbeddingBackend:
    """Factory : construit le bon backend selon la configuration."""
    if settings.embedding_provider == "bedrock":
        return BedrockEmbeddingBackend(
            model_id=settings.bedrock_embedding_model,
            region=settings.aws_region,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
        )
    return LocalEmbeddingBackend(model_name=settings.embedding_model)


class Embedder:
    """
    Point d'entrée unique utilisé par le pipeline pour vectoriser des chunks.
    Encapsule le choix du backend (local ou Bedrock) derrière une interface
    stable — le pipeline ne sait jamais laquelle des deux est utilisée.
    """

    def __init__(self, backend: Optional[EmbeddingBackend] = None):
        self._backend = backend or _build_backend()

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """
        Calcule l'embedding de chaque chunk et le remplit sur place.
        Retourne la même liste de chunks, avec `chunk.embedding` rempli.
        """
        if not chunks:
            return chunks

        texts = [c.content for c in chunks]
        vectors = self._backend.encode(texts)

        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = vector

        return chunks