"""Dominio del motor predictivo.

Un `ForecastResult` es la proyección de un costo a futuro: cuánto cuesta hoy,
cuánto costará en N meses y la variación %. El cómputo lo hace un `Forecaster`
(puerto): hoy determinístico (fórmula con una tasa), mañana ML (Prophet/XGBoost)
— mismo contrato. La `monthly_rate` es un PARÁMETRO (inflación/ICC), no un valor
aprendido, mientras estemos en la Vía A.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.cost_intelligence.domain.value_objects import Money

_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class ForecastResult:
    cost_today: Money
    projected_cost: Money
    horizon_months: int
    monthly_rate: Decimal
    method: str

    @property
    def variation_pct(self) -> Decimal:
        """Variación % entre hoy y el proyectado."""
        if self.cost_today.amount == 0:
            return Decimal("0")
        return ((self.projected_cost.amount / self.cost_today.amount) - 1) * _HUNDRED
