"""Repo SQLAlchemy del histórico de precios. Implementa `PriceHistoryRepository`.

Al registrar un precio sincroniza `Material.unit_price` (cache del precio
vigente que consume el motor de cómputo actual) → una sola escritura mantiene
coherentes histórico y precio vigente.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.application.ports import PriceHistoryRepository
from app.cost_intelligence.domain.pricing import PricePoint
from app.cost_intelligence.domain.value_objects import Money
from app.models.material import Material
from app.models.price_history import MaterialPriceHistory


def _to_dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _to_point(row: MaterialPriceHistory) -> PricePoint:
    return PricePoint(
        material_id=row.material_id,
        price=Money(row.price),
        observed_on=row.date.date(),
        source=row.source,
    )


class SqlPriceHistoryRepository(PriceHistoryRepository):
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, point: PricePoint) -> PricePoint:
        amount = float(point.price.amount)
        self._s.add(MaterialPriceHistory(
            material_id=point.material_id,
            price=amount,
            date=_to_dt(point.observed_on),
            source=point.source,
        ))
        material = self._s.get(Material, point.material_id)
        if material is not None:
            material.unit_price = amount  # cache de precio vigente
        self._s.flush()
        return point

    def latest(self, material_id: int) -> Optional[PricePoint]:
        row = self._s.scalars(
            select(MaterialPriceHistory)
            .where(MaterialPriceHistory.material_id == material_id)
            .order_by(MaterialPriceHistory.date.desc())
            .limit(1)
        ).first()
        return _to_point(row) if row else None

    def series(self, material_id: int, since: Optional[date] = None) -> list[PricePoint]:
        stmt = select(MaterialPriceHistory).where(
            MaterialPriceHistory.material_id == material_id
        )
        if since is not None:
            stmt = stmt.where(MaterialPriceHistory.date >= _to_dt(since))
        stmt = stmt.order_by(MaterialPriceHistory.date.asc())
        return [_to_point(r) for r in self._s.scalars(stmt).all()]

    def has_history(self, material_id: int) -> bool:
        return self._s.scalars(
            select(MaterialPriceHistory.id)
            .where(MaterialPriceHistory.material_id == material_id)
            .limit(1)
        ).first() is not None
