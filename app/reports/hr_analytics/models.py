"""
Modèles Pydantic pour le dashboard "Rapport de productivité RH".

Ces modèles définissent le contrat de sortie de l'API — aucune logique
ici, juste la forme des données (SRP : la logique vit dans aggregator.py
et repository.py).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class KpiSummaryOut(BaseModel):
    """Les 4 cartes KPI en haut du dashboard."""
    tickets_traites:        int
    tickets_traites_delta:  Optional[float] = None   # variation en % vs période précédente
    tickets_resolus:        int
    tickets_resolus_delta:  Optional[float] = None
    temps_moyen_heures:     Optional[float] = None
    satisfaction_moyenne:   Optional[float] = None    # 0-1


class EmployeeProductivityOut(BaseModel):
    """Une ligne de la barre de productivité par collaborateur."""
    employee_id:   str
    display_name:  str
    team:          Optional[str] = None
    tickets_count: int


class BestEmployeeOut(BaseModel):
    """Carte 'Meilleur collaborateur' — meilleur score composite."""
    employee_id:          str
    display_name:         str
    team:                 Optional[str] = None
    tickets_resolus:      int
    temps_moyen_heures:   Optional[float] = None
    satisfaction_moyenne: Optional[float] = None


class EmployeeDetailOut(BaseModel):
    """Une ligne de la table 'Détail des collaborateurs'."""
    employee_id:          str
    display_name:         str
    team:                 Optional[str] = None
    tickets_assignes:     int
    tickets_resolus:      int
    temps_moyen_heures:   Optional[float] = None
    satisfaction_moyenne: Optional[float] = None


class DashboardOut(BaseModel):
    """Réponse complète du dashboard — un seul GET, un seul contrat."""
    kpis:              KpiSummaryOut
    productivite:      list[EmployeeProductivityOut]
    meilleur_employe:  Optional[BestEmployeeOut] = None
    synthese_ia:       Optional[str] = None
    detail:            list[EmployeeDetailOut]
    period_start:      Optional[datetime] = None
    period_end:        Optional[datetime] = None


class TicketScoreOut(BaseModel):
    """Sortie brute d'un scoring LLM pour un ticket — utilisée en
    interne par satisfaction_scorer.py et stockée telle quelle."""
    ticket_id:          str
    source_type:        str
    is_closed:           bool
    resolution_hours:    Optional[float] = None
    complexity_score:    float
    satisfaction_score:  float
    llm_reasoning:       str
    prompt_version:      str