"""
Interface abstraite que tout transformer de source doit implémenter.

Un transformer a une seule responsabilité : convertir un RawRecord (donnée
brute, spécifique au format natif de la source) en une liste de Chunk
(texte prêt à être vectorisé, dans un format générique partagé).

Le transformer ne fait AUCUN appel réseau et ne connaît pas le connecteur
qui a produit le RawRecord — il reçoit la donnée, il la transforme, c'est
tout (Single Responsibility Principle).

Pourquoi une interface séparée de BaseConnector plutôt qu'une seule classe
qui ferait les deux ? Parce que récupération et transformation évoluent
indépendamment : on peut changer la logique de chunking sans toucher au
client HTTP, et inversement (Open/Closed Principle).
"""

from abc import ABC, abstractmethod

from app.core.models import Chunk, RawRecord


class BaseTransformer(ABC):

    @abstractmethod
    def transform(self, record: RawRecord) -> list[Chunk]:
        """
        Transforme un enregistrement brut en une liste de chunks prêts
        à être vectorisés.

        Args:
            record: la donnée brute telle que retournée par un connecteur.

        Returns:
            Liste de Chunk. Peut être vide si l'enregistrement ne contient
            rien d'exploitable (ex: ticket vide, contenu filtré).
            Peut contenir plusieurs chunks pour un seul record (ex: un
            chunk pour le corps, un chunk par commentaire).
        """
        ...