"""
Agent Documents Clients — implémentation concrète de BaseAgent pour le schéma `documents`.

Permet la recherche RAG sur tous les fichiers importés par les utilisateurs
(PDF, DOCX, TXT, CSV, PPTX...). Toute la logique de recherche parallèle
(Vector + BM25 + SQL metadata) et fusion RRF est héritée de BaseAgent.
"""

from app.rag.agents.base_agent import BaseAgent


class DocumentsAgent(BaseAgent):
    source_type = "documents"
