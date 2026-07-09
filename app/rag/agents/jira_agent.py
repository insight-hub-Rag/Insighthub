"""
Agent Jira — implémentation concrète de BaseAgent pour le schéma `jira`.

Ne fait que déclarer le schéma cible. Toute la logique (recherche
vectorielle + SQL + BM25 en parallèle, fusion RRF interne, mesure de
latence) est héritée de BaseAgent — c'est la preuve que l'architecture
générique fonctionne : un nouvel agent = quelques lignes.
"""

from app.rag.agents.base_agent import BaseAgent


class JiraAgent(BaseAgent):
    source_type = "jira"