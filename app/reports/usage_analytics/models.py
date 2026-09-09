"""
app/reports/usage_analytics/models.py

Dataclasses du module Usage Analytics — aucune logique, uniquement
la forme des données échangées entre repository et router.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestLogEntry:
    """Une ligne de log = une requête utilisateur (question posée via /search)."""
    question:       str
    source:         str
    latency_ms:     float
    input_tokens:   int
    output_tokens:  int
    cost_usd:       float
    model:          Optional[str] = None


@dataclass
class UsageStats:
    """Agrégats affichés dans les cartes KPI du dashboard."""
    total_requests:  int
    avg_latency_ms:  float
    top_source:      str
    avg_cost_usd:    float
    total_cost_usd:  float