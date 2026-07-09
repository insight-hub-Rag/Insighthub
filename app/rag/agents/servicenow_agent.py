"""
Agent ServiceNow — implémentation concrète de BaseAgent pour le schéma
`servicenow`.

⚠️ Aucun connecteur ServiceNow n'existe dans ce projet actuellement
(pas de app/connectors/servicenow/, pas de schéma dans postgres/init.sql,
pas d'entrée dans sql_retriever.ALLOWED_FILTER_KEYS). Cet agent est un
placeholder prêt à fonctionner dès que ces trois éléments existeront :
- schema_exists() retournera False tant que le schéma SQL n'existe pas
  → l'agent retourne des résultats vides proprement, sans erreur.
- Ne pas activer ce schéma dans agents/registry.py tant que l'ingestion
  ServiceNow n'est pas prête (sinon le router pourrait le sélectionner
  pour rien).
"""

from app.rag.agents.base_agent import BaseAgent


class ServiceNowAgent(BaseAgent):
    source_type = "servicenow"