"""
Interface abstraite que tout connecteur de source doit implémenter.

Chaque nouvelle source (Jira, ServiceNow, SharePoint...) crée une classe
qui hérite de BaseConnector et implémente les méthodes abstraites.

C'est la pièce centrale du Strategy Pattern : `IngestionPipeline` ne
connaît jamais une source concrète, seulement ce contrat. Ajouter une
nouvelle source ne nécessite donc aucune modification du pipeline
(principe Open/Closed).

Le connecteur a une seule responsabilité : RÉCUPÉRER les données brutes
depuis la source externe. Il ne transforme pas le contenu et ne le stocke
pas — ça, c'est le rôle du transformer et du vector_store respectivement.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from app.core.models import RawRecord


class BaseConnector(ABC):

    @property
    @abstractmethod
    def source_type(self) -> str:
        """
        Identifiant unique de la source.
        Exemples : 'jira', 'servicenow', 'sharepoint'.
        Utilisé pour le routing (schéma DB, logs, métadonnées).
        """
        ...

    @abstractmethod
    def fetch(self, since: Optional[str] = None) -> AsyncGenerator[RawRecord, None]:
        """
        Génère les enregistrements bruts depuis la source, un par un.

        Args:
            since: curseur optionnel pour une synchronisation incrémentale
                   (ex: timestamp ISO). Si None, récupère tout (full sync).

        Yields:
            RawRecord — un enregistrement brut à la fois. On utilise un
            générateur async pour ne jamais charger toute la source en
            mémoire d'un coup.
        """
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Vérifie que la connexion à la source externe fonctionne
        (credentials valides, endpoint accessible).
        Retourne True si OK, False sinon. Utilisé avant de lancer un sync
        complet pour échouer rapidement avec un message clair.
        """
        ...