"""Repo SQLAlchemy del histórico de mano de obra. Implementa
`LaborRateHistoryRepository`. Al registrar un costo sincroniza
`LaborRate.daily_cost` (cache del costo vigente). Mirror de
`SqlPriceHistoryRepository`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.application.ports import LaborRateHistoryRepository
from app.cost_intelligence.domain.labor import LaborRatePoint
from app.cost_intelligence.domain.value_objects import Money
from app.models.labor import LaborRate, LaborRateHistory


def _to_dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _to_point(row: LaborRateHistory) -> LaborRatePoint:
    return LaborRatePoint(
        labor_rate_id=row.labor_rate_id,
        daily_cost=Money(row.daily_cost),
        observed_on=row.date.date(),
        source=row.source,
    )


class SqlLaborRateHistoryRepository(LaborRateHistoryRepository):
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, point: LaborRatePoint) -> LaborRatePoint:
        amount = float(point.daily_cost.amount)
        self._s.add(LaborRateHistory(
            labor_rate_id=point.labor_rate_id,
            daily_cost=amount,
            date=_to_dt(point.observed_on),
            source=point.source,
        ))
        rate = self._s.get(LaborRate, point.labor_rate_id)
        if rate is not None:
            rate.daily_cost = amount  # cache de costo vigente
        self._s.flush()
        return point

    def latest(self, labor_rate_id: int) -> Optional[LaborRatePoint]:
        row = self._s.scalars(
            select(LaborRateHistory)
            .where(LaborRateHistory.labor_rate_id == labor_rate_id)
            .order_by(LaborRateHistory.date.desc())
            .limit(1)
        ).first()
        return _to_point(row) if row else None

    def series(self, labor_rate_id: int, since: Optional[date] = None) -> list[LaborRatePoint]:
        stmt = select(LaborRateHistory).where(
            LaborRateHistory.labor_rate_id == labor_rate_id
        )
        if since is not None:
            stmt = stmt.where(LaborRateHistory.date >= _to_dt(since))
        stmt = stmt.order_by(LaborRateHistory.date.asc())
        return [_to_point(r) for r in self._s.scalars(stmt).all()]

    def has_history(self, labor_rate_id: int) -> bool:
        return self._s.scalars(
            select(LaborRateHistory.id)
            .where(LaborRateHistory.labor_rate_id == labor_rate_id)
            .limit(1)
        ).first() is not None
