"""Jornales de la empresa: costo por día de cada oficio (con cargas sociales)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.labor import LaborRate
from app.services.budget_rules import DEFAULT_TRADES


def ensure_rates(organization_id: int, db: Session) -> list[LaborRate]:
    """Oficios activos de la org; si no tiene ninguno, siembra los de por
    defecto en $ 0 (los completa el admin)."""
    rates = list(db.scalars(
        select(LaborRate).where(LaborRate.organization_id == organization_id,
                                LaborRate.active.is_(True)).order_by(LaborRate.id)
    ).all())
    if not rates:
        rates = [LaborRate(organization_id=organization_id, trade=t, daily_cost=0.0)
                 for t in DEFAULT_TRADES]
        db.add_all(rates)
        db.flush()
    return rates


def trade_costs(organization_id: int, db: Session) -> dict[str, float]:
    return {r.trade: r.daily_cost for r in ensure_rates(organization_id, db)}
