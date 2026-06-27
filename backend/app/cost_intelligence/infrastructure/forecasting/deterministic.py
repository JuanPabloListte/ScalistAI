"""Forecaster determinístico (Vía A): interés compuesto sobre una tasa mensual.

    projected = amount × (1 + monthly_rate) ^ horizon_months

La `monthly_rate` es un PARÁMETRO (inflación esperada o ICC), no un valor
aprendido. Es el bootstrap honesto mientras no haya serie histórica para ML.
Cuando la haya, un `ProphetForecaster`/`XGBoostForecaster` implementa el mismo
puerto y este adapter se reemplaza sin tocar nada más.
"""
from __future__ import annotations

from decimal import Decimal

from app.cost_intelligence.application.forecast_ports import Forecaster
from app.cost_intelligence.domain.forecast import ForecastResult
from app.cost_intelligence.domain.value_objects import Money

_ONE = Decimal("1")


class DeterministicForecaster(Forecaster):
    def __init__(self, monthly_rate: Decimal, method: str = "deterministic") -> None:
        self._rate = monthly_rate
        self._method = method

    def project(self, amount: Money, horizon_months: int) -> ForecastResult:
        factor = (_ONE + self._rate) ** horizon_months
        projected = Money(amount.amount * factor, amount.currency).rounded()
        return ForecastResult(
            cost_today=amount.rounded(),
            projected_cost=projected,
            horizon_months=horizon_months,
            monthly_rate=self._rate,
            method=self._method,
        )
