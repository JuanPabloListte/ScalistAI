"""Dominio de precios.

Un `PricePoint` es el precio de un material en una fecha, con su **fuente** (de
dónde salió: backfill, manual, INDEC, proveedor…). Inmutable. La serie de
PricePoints por material es la base del motor predictivo (Fase 4).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.cost_intelligence.domain.value_objects import Money


@dataclass(frozen=True, slots=True)
class PricePoint:
    material_id: int
    price: Money
    observed_on: date
    source: str = "manual"

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("PricePoint requiere una fuente (source)")
        if self.price.amount < 0:
            raise ValueError("El precio no puede ser negativo")
