"""DTOs de configuración de costos indirectos (Módulo 4)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CostSettingsRead(BaseModel):
    overhead_pct: float   # gastos generales (0.15 = 15%)
    profit_pct: float     # beneficio
    iva_pct: float


class CostSettingsUpdate(BaseModel):
    overhead_pct: Optional[float] = None
    profit_pct: Optional[float] = None
    iva_pct: Optional[float] = None
