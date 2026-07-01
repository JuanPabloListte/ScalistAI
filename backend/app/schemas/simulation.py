"""DTOs del simulador de escenarios (Módulo 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SimulationCreate(BaseModel):
    plan_id: int
    name: Optional[str] = None
    page: Optional[int] = None
    # selección de recetas por entidad: { "wall": 12, "roof": 8 }. Si falta, usa defaults.
    selection: Optional[dict[str, int]] = None


class TotalsOut(BaseModel):
    materials: float
    labor_cost: float
    labor_hours: float
    duration_days: float


class MaterialLineOut(BaseModel):
    material_id: int
    material_name: str
    quantity: float
    unit: str
    unit_cost: float
    total: float


class SimulationRead(BaseModel):
    id: int
    plan_id: int
    name: str
    status: str
    created_at: datetime
    totals: TotalsOut
    lines: list[MaterialLineOut]


class CompareRequest(BaseModel):
    plan_id: int
    entity_type: str
    recipe_a: int
    recipe_b: int
    page: Optional[int] = None


class CompareResponse(BaseModel):
    """Coincide con el ejemplo del Módulo 2 de la propuesta."""
    original: str
    alternative: str
    material_cost_difference: float
    labor_cost_difference: float
    time_saved_days: float
