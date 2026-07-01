"""Caso de uso: registrar un precio nuevo de un material.

Agrega un punto al histórico; el repo se encarga de sincronizar el precio
vigente (`Material.unit_price`) que consume el motor de cómputo actual.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.cost_intelligence.application.ports import PriceHistoryRepository
from app.cost_intelligence.domain.pricing import PricePoint
from app.cost_intelligence.domain.value_objects import Money, Numeric


class RecordMaterialPrice:
    def __init__(self, repo: PriceHistoryRepository) -> None:
        self._repo = repo

    def execute(
        self,
        material_id: int,
        amount: Numeric,
        *,
        source: str = "manual",
        observed_on: Optional[date] = None,
        currency: str = "ARS",
    ) -> PricePoint:
        point = PricePoint(
            material_id=material_id,
            price=Money(amount, currency),
            observed_on=observed_on or date.today(),
            source=source,
        )
        return self._repo.add(point)
