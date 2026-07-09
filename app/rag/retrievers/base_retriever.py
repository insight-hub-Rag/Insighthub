"""
Base commune à tous les retrievers (vector, sql, bm25).

Chaque retriever cherche dans UN schéma PostgreSQL donné (jira, servicenow,
confluence...) et retourne une liste de RetrievedChunk. Cette classe
factorise ce qui est identique entre les 3 méthodes : la connexion DB
et la vérification qu'un schéma/table existe avant d'interroger dessus
(utile pour les sources pas encore ingérées, ex: sharepoint).
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import psycopg2
from pgvector.psycopg2 import register_vector

from config import settings
from app.core.models import RetrievedChunk

logger = logging.getLogger(__name__)

# Schémas SQL disponibles, mappés à leur nom de source logique.
# Une seule source de vérité, réutilisée par tous les retrievers/agents.
SOURCES = {
    "jira":        "jira",
    "servicenow":  "servicenow",
    "sharepoint":  "sharepoint",
    "confluence":  "confluence",
}


def get_connection():
    """
    Connexion psycopg2 partagée, avec le type `vector` enregistré
    (nécessaire pour que pgvector.psycopg2 sache sérialiser/désérialiser
    les colonnes `vector` de PostgreSQL).
    """
    conn = psycopg2.connect(settings.database_url_sync)
    register_vector(conn)
    return conn


def schema_exists(conn, schema: str, table: str = "embeddings") -> bool:
    """
    Vérifie qu'un schéma/table existe avant d'interroger dessus.
    Évite un crash si une source n'a pas encore été ingérée
    (ex: sharepoint bloqué par l'auth OFPPT).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            )
            """,
            (schema, table),
        )
        return bool(cur.fetchone()[0])


class BaseRetriever(ABC):
    """
    Contrat abstrait pour une méthode de recherche brute.
    Implémenté par VectorRetriever, SQLRetriever, BM25Retriever.
    """

    @abstractmethod
    def search(
        self,
        schema: str,
        query_text: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> list[RetrievedChunk]:
        """
        Cherche dans le schéma donné et retourne les top_k chunks
        les plus pertinents pour cette méthode, triés par score
        décroissant. Ne lève jamais d'exception vers l'appelant :
        en cas d'erreur ou de schéma absent, retourne une liste vide
        et logue un warning (pour ne pas faire échouer tout le pipeline
        si une seule source a un problème).
        """
        ...