"""Costos indirectos: convierte el COSTO DIRECTO (materiales + mano de obra) en
el PRECIO DE VENTA cotizable, aplicando los márgenes estándar de obra.

    directo
      + gastos generales (% sobre directo)   = subtotal de costo
      + beneficio        (% sobre subtotal)   = precio neto (sin IVA)
      + IVA              (% sobre neto)        = PRECIO FINAL

Las tasas son PARÁMETROS configurables por organización (gastos generales y
beneficio los fija cada estudio; IVA = 21% legal en Argentina). No son data
aprendida ni inventada.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.cost_intelligence.domain.value_objects import Money


@dataclass(frozen=True, slots=True)
class IndirectRates:
    overhead_pct: Decimal   # gastos generales, ej. 0.15 = 15%
    profit_pct: Decimal     # beneficio, ej. 0.10 = 10%
    iva_pct: Decimal        # ej. 0.21 = 21%

    def __post_init__(self) -> None:
        for name in ("overhead_pct", "profit_pct", "iva_pct"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} no puede ser negativo")


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    direct: Money       # costo directo (materiales + MO)
    overhead: Money     # gastos generales
    profit: Money       # beneficio
    net: Money          # precio neto (sin IVA)
    iva: Money
    total: Money        # precio final de venta


def build_price(direct: Money, rates: IndirectRates) -> PriceBreakdown:
    overhead = direct * rates.overhead_pct
    cost_subtotal = direct + overhead
    profit = cost_subtotal * rates.profit_pct
    net = cost_subtotal + profit
    iva = net * rates.iva_pct
    total = net + iva
    return PriceBreakdown(
        direct=direct.rounded(),
        overhead=overhead.rounded(),
        profit=profit.rounded(),
        net=net.rounded(),
        iva=iva.rounded(),
        total=total.rounded(),
    )
