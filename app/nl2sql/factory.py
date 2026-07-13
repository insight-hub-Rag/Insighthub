"""
app/nl2sql/factory.py

Point de construction unique du NL2SQLAgent, assemblé depuis settings.
Séparé de orchestrator.py pour garder NL2SQLAgent testable en isolation
(dépendances injectées, pas lues depuis l'environnement directement).

Instance unique réutilisée entre les requêtes — même pattern que
_orchestrator dans app/api/router.py.
"""

from config import settings
from app.nl2sql.models import NL2SQLConfig
from app.nl2sql.orchestrator import NL2SQLAgent
from app.nl2sql.query_generator import QueryGenerator
from app.nl2sql.query_optimizer import QueryOptimizer
from app.nl2sql.response_formatter import ResponseFormatter
from app.nl2sql.schema_cache import InMemorySchemaCache
from app.nl2sql.schema_store import SchemaStore

_agent_instance: NL2SQLAgent | None = None


def build_nl2sql_agent() -> NL2SQLAgent:
    global _agent_instance
    if _agent_instance is not None:
        return _agent_instance

    config = NL2SQLConfig(
        connection_id="default",
        database_url=settings.nl2sql_target_db_url,
        latency_threshold_ms=settings.nl2sql_latency_threshold_ms,
        schema_cache_ttl_seconds=settings.nl2sql_schema_ttl_seconds,
    )

    store = SchemaStore()
    # InMemory pour l'instant — RedisSchemaCache prêt à brancher plus
    # tard sans toucher au reste (voir schema_cache.py, étape 6).
    cache = InMemorySchemaCache(store, ttl_seconds=config.schema_cache_ttl_seconds)

    query_generator = QueryGenerator(
        bedrock_model_id=settings.bedrock_text_model,
        aws_region=settings.aws_region,
    )
    query_optimizer = QueryOptimizer(
        bedrock_model_id=settings.bedrock_text_model,
        aws_region=settings.aws_region,
    )
    response_formatter = ResponseFormatter(
        bedrock_model_id=settings.bedrock_text_model,
        aws_region=settings.aws_region,
    )

    _agent_instance = NL2SQLAgent(
        config=config,
        schema_cache=cache,
        query_generator=query_generator,
        query_optimizer=query_optimizer,
        response_formatter=response_formatter,
    )
    return _agent_instance