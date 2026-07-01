"""Puertos del motor predictivo.

`Forecaster` es la abstracción clave: hoy la implementa el determinístico (Vía A)
y mañana el ML (Vía B: Prophet/XGBoost) — los casos de uso y la API no cambian.
`MacroRateProvider` deriva una tasa mensual desde el histórico de un índice
oficial (ICC/IPC/dólar) cuando esté cargado.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from app.cost_intelligence.domain.forecast import ForecastResult
from app.cost_intelligence.domain.value_objects import Money


class Forecaster(ABC):
    @abstractmethod
    def project(self, amount: Money, horizon_months: int) -> ForecastResult:
        """Proyecta `amount` a `horizon_months` meses."""


class MacroRateProvider(ABC):
    @abstractmethod
    def monthly_rate(self, indicator: str) -> Optional[Decimal]:
        """Tasa mensual compuesta derivada del histórico del índice, o None si
        no hay datos suficientes (entonces el caller debe pedir una tasa explícita)."""
