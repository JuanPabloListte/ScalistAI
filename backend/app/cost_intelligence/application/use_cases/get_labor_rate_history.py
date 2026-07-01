"""Caso de uso: serie histórica del costo diario de un oficio (para graficar y
proyectar la evolución de salarios)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.cost_intelligence.application.ports import LaborRateHistoryRepository
from app.cost_intelligence.domain.labor import LaborRatePoint


class GetLaborRateHistory:
    def __init__(self, repo: LaborRateHistoryRepository) -> None:
        self._repo = repo

    def execute(self, labor_rate_id: int, since: Optional[date] = None) -> list[LaborRatePoint]:
        return self._repo.series(labor_rate_id, since)
