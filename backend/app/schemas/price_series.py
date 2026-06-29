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
