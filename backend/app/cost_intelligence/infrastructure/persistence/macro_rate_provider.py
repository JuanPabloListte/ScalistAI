"""Deriva la tasa mensual compuesta desde el histórico de un índice macro.

Toma los últimos puntos del indicador (ej. ICC) y calcula la tasa mensual
compuesta entre el más viejo y el más nuevo de la ventana:

    rate = (valor_nuevo / valor_viejo) ^ (1 / intervalos) − 1

Si no hay ≥2 puntos, devuelve None (el caller debe pedir una tasa explícita).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.application.forecast_ports import MacroRateProvider
from app.models.macro_series import MacroSeries

_DEFAULT_WINDOW = 6  # últimos N puntos para estimar la tendencia


class SqlMacroRateProvider(MacroRateProvider):
    def __init__(self, session: Session, window: int = _DEFAULT_WINDOW) -> None:
        self._s = session
        self._window = window

    def monthly_rate(self, indicator: str) -> Optional[Decimal]:
        rows = self._s.scalars(
            select(MacroSeries)
            .where(MacroSeries.indicator == indicator)
            .order_by(MacroSeries.date.desc())
            .limit(self._window)
        ).all()
        if len(rows) < 2:
            return None
        newest, oldest = rows[0], rows[-1]
        if oldest.value <= 0:
            return None
        intervals = len(rows) - 1
        rate = (newest.value / oldest.value) ** (1.0 / intervals) - 1.0
        return Decimal(str(round(rate, 6)))
