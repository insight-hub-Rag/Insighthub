import json
import logging
import time
from typing import Optional, Protocol

from loguru import logger

from config import settings
from app.core.models import Chunk


class EmbeddingBackend(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class LocalEmbeddingBackend:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        logger.info(f"[Embedder] Chargement modèle local : {model_name}")
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]


class BedrockEmbeddingBackend:
    def __init__(self):
        import boto3
        self._client = boto3.client(
            "bedrock-runtime",
            region_name           = settings.aws_region,
            aws_access_key_id     = settings.aws_access_key_id,
            aws_secret_access_key = settings.aws_secret_access_key,
        )
        self._model_id = "amazon.titan-embed-text-v2:0"
        logger.info(f"[Embedder] Bedrock Titan Embed v2 | region={settings.aws_region}")

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            body = json.dumps({
                "inputText":  text[:8000],
                "dimensions": 1024,
                "normalize":  True,
            })
            resp   = self._client.invoke_model(
                modelId     = self._model_id,
                body        = body,
                contentType = "application/json",
                accept      = "application/json",
            )
            result = json.loads(resp["body"].read())
            vectors.append(result["embedding"])
        return vectors


def _build_backend() -> EmbeddingBackend:
    if settings.embedding_provider == "bedrock" and settings.aws_access_key_id:
        return BedrockEmbeddingBackend()
    logger.info("[Embedder] Fallback local")
    return LocalEmbeddingBackend(model_name=settings.embedding_model)


class Embedder:
    def __init__(self, backend: Optional[EmbeddingBackend] = None):
        self._backend = backend or _build_backend()

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return chunks

        t0      = time.time()
        texts   = [c.content for c in chunks]
        vectors = self._backend.encode(texts)
        elapsed = time.time() - t0

        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = vector

        logger.info(
            f"[Embedder] {len(chunks)} chunks | "
            f"temps={elapsed:.3f}s | "
            f"moy={elapsed/len(chunks)*1000:.1f}ms/chunk | "
            f"dims={len(vectors[0]) if vectors else 0}"
        )
        return chunks