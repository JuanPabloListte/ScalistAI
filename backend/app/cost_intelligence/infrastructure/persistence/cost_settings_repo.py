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

# Rubros que el modelo (IFC/plano) normalmente NO trae, estimados como % sobre la
# OBRA GRIS (materiales + MO de lo modelado: estructura + mampostería + aberturas).
# Porcentajes de referencia del cómputo tradicional argentino; EDITABLES por org.
# No son data del modelo: son una estimación paramétrica explícita.
DEFAULT_PARAMETRIC_RUBROS: list[dict] = [
    {"key": "fundaciones", "label": "Fundaciones y movimiento de suelo", "pct": 0.25},
    {"key": "inst_electrica", "label": "Instalación eléctrica", "pct": 0.22},
    {"key": "inst_sanitaria", "label": "Instalación sanitaria y cloacal", "pct": 0.18},
    {"key": "inst_gas", "label": "Instalación de gas", "pct": 0.05},
    {"key": "terminaciones", "label": "Terminaciones (revoques, pisos, pintura, cielorrasos)", "pct": 0.70},
    {"key": "carpinteria_madera", "label": "Carpintería de madera y varios", "pct": 0.15},
]


def _clean_rubros(raw) -> list[dict]:
    """Normaliza la lista guardada (o defaults) a {key,label,pct} válidos."""
    if not raw:
        return [dict(r) for r in DEFAULT_PARAMETRIC_RUBROS]
    out = []
    for r in raw:
        try:
            out.append({"key": str(r["key"]), "label": str(r["label"]), "pct": float(r["pct"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out or [dict(r) for r in DEFAULT_PARAMETRIC_RUBROS]


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

    def parametric_rubros(self, organization_id: int) -> list[dict]:
        """Rubros paramétricos de la org (o defaults si no configuró)."""
        s = self.get_or_create(organization_id)
        return _clean_rubros(s.parametric_rubros)

    def update_parametric_rubros(self, organization_id: int, rubros: list[dict]) -> list[dict]:
        s = self.get_or_create(organization_id)
        s.parametric_rubros = _clean_rubros(rubros)
        self._s.flush()
        return s.parametric_rubros
