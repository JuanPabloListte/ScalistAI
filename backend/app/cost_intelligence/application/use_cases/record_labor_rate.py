"""Caso de uso: registrar el costo diario de un oficio.

Agrega un punto al histórico; el repo sincroniza el costo vigente
(`LaborRate.daily_cost`).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.cost_intelligence.application.ports import LaborRateHistoryRepository
from app.cost_intelligence.domain.labor import LaborRatePoint
from app.cost_intelligence.domain.value_objects import Money, Numeric


class RecordLaborRate:
    def __init__(self, repo: LaborRateHistoryRepository) -> None:
        self._repo = repo

    def execute(
        self,
        labor_rate_id: int,
        daily_cost: Numeric,
        *,
        source: str = "manual",
        observed_on: Optional[date] = None,
        currency: str = "ARS",
    ) -> LaborRatePoint:
        point = LaborRatePoint(
            labor_rate_id=labor_rate_id,
            daily_cost=Money(daily_cost, currency),
            observed_on=observed_on or date.today(),
            source=source,
        )
        return self._repo.add(point)
