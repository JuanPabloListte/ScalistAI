"""Caso de uso: proyectar un costo a futuro.

Thin sobre el `Forecaster` (la lógica de proyección vive en el adapter, para
poder swapear determinístico ↔ ML sin tocar esto).
"""
from __future__ import annotations

from app.cost_intelligence.application.forecast_ports import Forecaster
from app.cost_intelligence.domain.forecast import ForecastResult
from app.cost_intelligence.domain.value_objects import Money


class ForecastCost:
    def __init__(self, forecaster: Forecaster) -> None:
        self._forecaster = forecaster

    def execute(self, amount: Money, horizon_months: int) -> ForecastResult:
        if horizon_months <= 0:
            raise ValueError("El horizonte debe ser de al menos 1 mes")
        return self._forecaster.project(amount, horizon_months)
