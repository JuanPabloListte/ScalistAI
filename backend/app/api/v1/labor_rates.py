"""Jornales de la empresa: costo por día de cada oficio (con cargas sociales).

Los usa la mano de obra cotizada por jornal (cuadrilla propia). Cada cambio
queda en el historial (labor_rate_history) con su fecha.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_org_admin
from app.cost_intelligence.application.use_cases.record_labor_rate import RecordLaborRate
from app.cost_intelligence.infrastructure.persistence.labor_repository import (
    SqlLaborRateHistoryRepository,
)
from app.models.labor import LaborRate, LaborRateHistory
from app.models.user import User
from app.services.labor_rates import ensure_rates

router = APIRouter(prefix="/labor-rates", tags=["labor-rates"])


class LaborRateRead(BaseModel):
    trade: str
    daily_cost: float
    updated_on: date | None


class LaborRateIn(BaseModel):
    trade: str = Field(min_length=1, max_length=80)
    daily_cost: float = Field(ge=0)


def _org_id(user: User) -> int:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    return user.organization_id


def _read(rates: list[LaborRate], db: Session) -> list[LaborRateRead]:
    out = []
    for r in rates:
        last = db.scalar(select(LaborRateHistory.date)
                         .where(LaborRateHistory.labor_rate_id == r.id)
                         .order_by(LaborRateHistory.date.desc()))
        out.append(LaborRateRead(trade=r.trade, daily_cost=r.daily_cost,
                                 updated_on=last.date() if last else None))
    return out


@router.get("", response_model=list[LaborRateRead])
def list_labor_rates(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> list[LaborRateRead]:
    rates = ensure_rates(_org_id(user), db)
    db.commit()
    return _read(rates, db)


@router.put("", response_model=list[LaborRateRead])
def replace_labor_rates(payload: list[LaborRateIn], db: Session = Depends(get_db),
                        user: User = Depends(require_org_admin)) -> list[LaborRateRead]:
    """Reemplaza la tabla: crea los oficios nuevos, registra en el historial los
    costos que cambiaron y desactiva los que ya no están (no se borran: el
    historial queda)."""
    org_id = _org_id(user)
    names = [p.trade.strip() for p in payload]
    if len(set(n.lower() for n in names)) != len(names):
        raise HTTPException(status_code=400, detail="Hay oficios repetidos.")
    existing = {r.trade.lower(): r for r in db.scalars(
        select(LaborRate).where(LaborRate.organization_id == org_id)).all()}
    record = RecordLaborRate(SqlLaborRateHistoryRepository(db))
    keep = set()
    for p in payload:
        trade = p.trade.strip()
        rate = existing.get(trade.lower())
        if rate is None:
            rate = LaborRate(organization_id=org_id, trade=trade, daily_cost=0.0)
            db.add(rate)
            db.flush()
        rate.active = True
        rate.trade = trade
        keep.add(rate.id)
        if abs((rate.daily_cost or 0) - p.daily_cost) > 1e-9:
            record.execute(rate.id, p.daily_cost, source="manual")
    for rate in existing.values():
        if rate.id not in keep:
            rate.active = False
    db.commit()
    return _read(ensure_rates(org_id, db), db)
