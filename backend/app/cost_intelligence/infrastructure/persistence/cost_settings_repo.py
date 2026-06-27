"""Repo de configuración de costos indirectos. Crea defaults si la org no tiene
y traduce a `IndirectRates` del dominio.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.domain.pricing_breakdown import IndirectRates
from app.models.cost_settings import CostSettings


class SqlCostSettingsRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_or_create(self, organization_id: int) -> CostSettings:
        s = self._s.scalars(
            select(CostSettings).where(CostSettings.organization_id == organization_id)
        ).first()
        if s is None:
            s = CostSettings(organization_id=organization_id,
                             overhead_pct=0.15, profit_pct=0.10, iva_pct=0.21)
            self._s.add(s)
            self._s.flush()
        return s

    def rates(self, organization_id: int) -> IndirectRates:
        s = self.get_or_create(organization_id)
        return IndirectRates(
            overhead_pct=Decimal(str(s.overhead_pct)),
            profit_pct=Decimal(str(s.profit_pct)),
            iva_pct=Decimal(str(s.iva_pct)),
        )

    def update(self, organization_id: int, *, overhead_pct: Optional[float] = None,
               profit_pct: Optional[float] = None, iva_pct: Optional[float] = None) -> CostSettings:
        s = self.get_or_create(organization_id)
        if overhead_pct is not None:
            s.overhead_pct = overhead_pct
        if profit_pct is not None:
            s.profit_pct = profit_pct
        if iva_pct is not None:
            s.iva_pct = iva_pct
        self._s.flush()
        return s
