"""
Agent SharePoint — implémentation concrète de BaseAgent pour le schéma
`sharepoint`. L'authentification OFPPT étant bloquée côté ingestion,
ce schéma n'a probablement aucune donnée pour l'instant : `schema_exists()`
dans base_retriever.py gère ça proprement (retourne une liste vide sans
planter le pipeline), donc cet agent est sûr à activer même sans données.
"""

from app.rag.agents.base_agent import BaseAgent


class SharePointAgent(BaseAgent):
    source_type = "sharepoint"