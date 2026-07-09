"""
Agent Confluence — implémentation concrète de BaseAgent pour le schéma
`confluence`. Comme JiraAgent, ne fait que déclarer le schéma cible ;
toute la logique est héritée de BaseAgent.
"""

from app.rag.agents.base_agent import BaseAgent


class ConfluenceAgent(BaseAgent):
    source_type = "confluence"