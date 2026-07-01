"""Caso de uso: serie histórica de precios de un material.

Para graficar la evolución y alimentar al motor predictivo (Fase 4).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.cost_intelligence.application.ports import PriceHistoryRepository
from app.cost_intelligence.domain.pricing import PricePoint


class GetPriceSeries:
    def __init__(self, repo: PriceHistoryRepository) -> None:
        self._repo = repo

    def execute(self, material_id: int, since: Optional[date] = None) -> list[PricePoint]:
        return self._repo.series(material_id, since)
