"""
Agent Manager — lance en parallèle les agents des sources sélectionnées
par le router, via asyncio.gather(). Ne connaît que l'interface commune
des agents (via AgentRegistry) — jamais les détails de chaque source.

Gère les erreurs et les timeouts par agent individuellement : si un
agent plante ou traîne, les autres continuent normalement plutôt que
de faire échouer tout le pipeline.
"""

import asyncio
import logging

from app.core.models import PreprocessedQuery, RoutingDecision, AgentResult
from app.rag.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = 8.0


class AgentManager:

    def __init__(self, registry: AgentRegistry | None = None):
        self.registry = registry or AgentRegistry()

    async def run(
        self,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> list[AgentResult]:
        agents = []
        for source in routing.sources:
            agent = self.registry.get(source)
            if agent is not None:
                agents.append(agent)

        if not agents:
            logger.warning(
                f"[AgentManager] Aucun agent disponible pour sources={routing.sources}"
            )
            return []

        tasks = [
            self._run_with_timeout(agent, query, routing) for agent in agents
        ]
        results = await asyncio.gather(*tasks)

        logger.info(
            f"[AgentManager] {len(results)} agents exécutés | "
            f"sources={[r.source_type for r in results]}"
        )
        return results

    async def _run_with_timeout(
        self,
        agent,
        query: PreprocessedQuery,
        routing: RoutingDecision,
    ) -> AgentResult:
        try:
            return await asyncio.wait_for(
                agent.run(query, routing), timeout=AGENT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"[AgentManager] Timeout sur agent '{agent.source_type}'")
            return AgentResult(
                source_type=agent.source_type,
                chunks=[],
                latency_ms=AGENT_TIMEOUT_SECONDS * 1000,
                error=f"Timeout après {AGENT_TIMEOUT_SECONDS}s",
            )
        except Exception as e:
            logger.error(f"[AgentManager] Erreur sur agent '{agent.source_type}' : {e}")
            return AgentResult(
                source_type=agent.source_type,
                chunks=[],
                latency_ms=0.0,
                error=str(e),
            )