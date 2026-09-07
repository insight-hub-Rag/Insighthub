"""
Aggregator — logique métier du dashboard HR Analytics.

Responsabilité UNIQUE : transformer les données brutes (repository) en
DTOs de sortie (models.py). Aucun SQL ici — tout accès base passe par
HrAnalyticsRepository. Aucune route FastAPI ici non plus — ça vit dans
router.py.
"""

from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.reports.hr_analytics.models import (
    BestEmployeeOut,
    DashboardOut,
    EmployeeDetailOut,
    EmployeeProductivityOut,
    KpiSummaryOut,
)
from app.reports.hr_analytics.repository import HrAnalyticsRepository
from app.reports.hr_analytics.ai_synthesis import AiSynthesisGenerator

# Statuts considérés comme "résolu", selon la source. À ajuster si vos
# workflows Jira/ServiceNow utilisent d'autres libellés.
CLOSED_STATUSES = {
    "jira": {"Terminé", "Done", "Résolu", "Closed"},
    "servicenow": {"Closed", "Resolved"},
}


class HrAnalyticsAggregator:

    def __init__(
        self,
        repository: Optional[HrAnalyticsRepository] = None,
        synthesis: Optional["AiSynthesisGenerator"] = None,
    ):
        self._repo = repository or HrAnalyticsRepository()
        self._synthesis = synthesis or AiSynthesisGenerator()

    async def build_dashboard(
        self,
        session: AsyncSession,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> DashboardOut:
        current_tickets = await self._repo.fetch_raw_tickets(
            session, self._iso(period_start), self._iso(period_end)
        )
        previous_tickets = await self._fetch_previous_period(
            session, period_start, period_end
        )

        ticket_ids = [t["ticket_id"] for t in current_tickets]
        scores = await self._repo.fetch_ticket_scores(session, ticket_ids)
        scores_by_ticket = {(s["ticket_id"], s["source_type"]): s for s in scores}

        kpis = self._build_kpis(current_tickets, previous_tickets, scores_by_ticket)
        by_employee = self._group_by_employee(current_tickets, scores_by_ticket)
        productivite = self._build_productivity(by_employee)
        meilleur = self._build_best_employee(by_employee)
        detail = self._build_detail(by_employee)
        synthese_ia = self._synthesis.generate(
            kpis, meilleur.display_name if meilleur else None
        )

        return DashboardOut(
            kpis=kpis,
            productivite=productivite,
            meilleur_employe=meilleur,
            synthese_ia=synthese_ia,
            detail=detail,
            period_start=period_start,
            period_end=period_end,
        )

    # ── KPIs globaux ──

    def _build_kpis(
        self,
        current: list[dict],
        previous: list[dict],
        scores_by_ticket: dict,
    ) -> KpiSummaryOut:
        traites_now = len(current)
        traites_prev = len(previous)
        resolus_now = sum(1 for t in current if self._is_closed(t))
        resolus_prev = sum(1 for t in previous if self._is_closed(t))

        resolution_hours = [
            s["resolution_hours"]
            for s in scores_by_ticket.values()
            if s.get("resolution_hours") is not None
        ]
        satisfaction_values = [
            s["satisfaction_score"]
            for s in scores_by_ticket.values()
            if s.get("satisfaction_score") is not None
        ]

        return KpiSummaryOut(
            tickets_traites=traites_now,
            tickets_traites_delta=self._delta_pct(traites_now, traites_prev),
            tickets_resolus=resolus_now,
            tickets_resolus_delta=self._delta_pct(resolus_now, resolus_prev),
            temps_moyen_heures=self._avg(resolution_hours),
            satisfaction_moyenne=self._avg(satisfaction_values),
        )

    # ── Regroupement par employé ──

    def _group_by_employee(
        self, tickets: list[dict], scores_by_ticket: dict
    ) -> dict[str, dict]:
        grouped: dict[str, dict] = defaultdict(lambda: {
            "display_name": None, "tickets": [], "scores": [],
        })
        for t in tickets:
            name = t.get("assignee") or "Non assigné"
            grouped[name]["display_name"] = name
            grouped[name]["tickets"].append(t)
            score = scores_by_ticket.get((t["ticket_id"], t["source_type"]))
            if score:
                grouped[name]["scores"].append(score)
        return grouped

    def _build_productivity(self, by_employee: dict) -> list[EmployeeProductivityOut]:
        result = [
            EmployeeProductivityOut(
                employee_id=name,   # remplacé par un vrai UUID quand l'auth existera
                display_name=name,
                tickets_count=len(data["tickets"]),
            )
            for name, data in by_employee.items()
        ]
        return sorted(result, key=lambda e: e.tickets_count, reverse=True)

    def _build_best_employee(self, by_employee: dict) -> Optional[BestEmployeeOut]:
        """Meilleur = plus haut satisfaction moyenne parmi ceux ayant
        au moins un ticket résolu (pas juste le plus de tickets traités)."""
        candidates = []
        for name, data in by_employee.items():
            resolus = sum(1 for t in data["tickets"] if self._is_closed(t))
            if resolus == 0:
                continue
            satisfaction = self._avg([s["satisfaction_score"] for s in data["scores"]])
            candidates.append((satisfaction or 0.0, name, data, resolus))

        if not candidates:
            return None

        satisfaction, name, data, resolus = max(candidates, key=lambda c: c[0])
        resolution_hours = self._avg([s["resolution_hours"] for s in data["scores"] if s.get("resolution_hours")])

        return BestEmployeeOut(
            employee_id=name,
            display_name=name,
            tickets_resolus=resolus,
            temps_moyen_heures=resolution_hours,
            satisfaction_moyenne=satisfaction,
        )

    def _build_detail(self, by_employee: dict) -> list[EmployeeDetailOut]:
        result = []
        for name, data in by_employee.items():
            resolus = sum(1 for t in data["tickets"] if self._is_closed(t))
            resolution_hours = self._avg(
                [s["resolution_hours"] for s in data["scores"] if s.get("resolution_hours")]
            )
            satisfaction = self._avg(
                [s["satisfaction_score"] for s in data["scores"]]
            )
            result.append(EmployeeDetailOut(
                employee_id=name,
                display_name=name,
                tickets_assignes=len(data["tickets"]),
                tickets_resolus=resolus,
                temps_moyen_heures=resolution_hours,
                satisfaction_moyenne=satisfaction,
            ))
        return sorted(result, key=lambda e: e.tickets_assignes, reverse=True)

    # ── Helpers purs ──

    @staticmethod
    def _is_closed(ticket: dict) -> bool:
        closed = CLOSED_STATUSES.get(ticket["source_type"], set())
        return ticket.get("status") in closed

    @staticmethod
    def _avg(values: list[float]) -> Optional[float]:
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 2) if values else None

    @staticmethod
    def _delta_pct(now: int, previous: int) -> Optional[float]:
        if previous == 0:
            return None
        return round(((now - previous) / previous) * 100, 1)

    @staticmethod
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    async def _fetch_previous_period(
        self,
        session: AsyncSession,
        period_start: Optional[datetime],
        period_end: Optional[datetime],
    ) -> list[dict]:
        """Période précédente de même durée, pour calculer les deltas.
        Si aucune période n'est fournie (dashboard 'Toutes'), pas de
        comparaison possible — retourne une liste vide."""
        if period_start is None or period_end is None:
            return []
        duration = period_end - period_start
        prev_start = period_start - duration
        prev_end = period_start
        return await self._repo.fetch_raw_tickets(
            session, self._iso(prev_start), self._iso(prev_end)
        )