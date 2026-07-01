"""Dominio de mano de obra.

Un `LaborRatePoint` es el costo diario de un oficio (trade) en una fecha, con su
fuente. Mirror de `PricePoint`: la serie por oficio alimenta el proyectado de
costo de mano de obra (los salarios también inflan).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.cost_intelligence.domain.value_objects import Money


@dataclass(frozen=True, slots=True)
class LaborRatePoint:
    labor_rate_id: int
    daily_cost: Money
    observed_on: date
    source: str = "manual"

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("LaborRatePoint requiere una fuente (source)")
        if self.daily_cost.amount < 0:
            raise ValueError("El costo diario no puede ser negativo")
