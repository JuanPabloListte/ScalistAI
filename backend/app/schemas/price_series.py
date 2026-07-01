"""Schemas de la serie histórica de precios por producto canónico (MaterialGroup).

Consolida los PricePoint reales de todos los materiales equivalentes de un grupo
en una sola serie temporal, para graficarla en el frontend.
"""
from datetime import date

from pydantic import BaseModel


class PriceSeriesPoint(BaseModel):
    date: date
    price: float
    source: str


class PriceSeriesProduct(BaseModel):
    id: int
    name: str
    category: str
    unit: str
    points: list[PriceSeriesPoint]
    first_price: float
    last_price: float
    change_pct: float | None  # variación % primer→último punto (None si first=0)
    # Proyección por la SERIE PROPIA del material (Vía B-lite); cae a IPC si no
    # hay ≥2 puntos. Ver domain/material_trend.py.
    horizon_months: int
    projected_price: float
    forecast_rate: float            # tasa mensual usada
    forecast_method: str            # serie_propia | ipc | sin_dato
    forecast_variation_pct: float   # % hoy→proyectado
    ipc_monthly_rate: float | None  # tasa IPC, para comparar
    beats_inflation: bool | None    # True si sube más rápido que el IPC
