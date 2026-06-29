"""Schema del presupuesto COMPLETO del proyecto: desglose por rubro + resumen
de cómputo (takeoff de cantidades). Alimenta la pantalla de presupuesto.
"""
from pydantic import BaseModel


class BudgetCategory(BaseModel):
    name: str            # rubro (categoría del material) o "Mano de Obra"
    total: float
    pct: float           # % sobre el costo directo
    per_m2: float | None  # $/m² de superficie cubierta


class BudgetTakeoff(BaseModel):
    wall_ml: float       # metros lineales de muro
    wall_m2: float       # m² de muro (largo × alto)
    openings: int        # aberturas totales
    doors: int
    windows: int
    columns: int
    beams_ml: float
    roof_m2: float       # superficie de cubierta/losa
    cloaca_ml: float
    electricidad_ml: float
    rooms: int           # ambientes
    floor_m2: float      # superficie de piso (suma de ambientes)


class ProjectBudgetSummary(BaseModel):
    plan_id: int
    project_name: str
    area_m2: float       # superficie cubierta estimada
    materials_total: float
    labor_total: float
    labor_hours: float
    duration_days: float
    direct_cost: float
    sale_price: float
    cost_per_m2: float | None
    categories: list[BudgetCategory]
    takeoff: BudgetTakeoff
