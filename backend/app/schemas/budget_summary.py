"""Schema del presupuesto COMPLETO del proyecto: desglose por rubro + resumen
de cómputo (takeoff de cantidades). Alimenta la pantalla de presupuesto.
"""
from pydantic import BaseModel


class BudgetCategory(BaseModel):
    name: str            # rubro (categoría del material) o "Mano de Obra"
    total: float
    pct: float           # % sobre el costo directo
    per_m2: float | None  # $/m² de superficie cubierta
    parametric: bool = False  # True si es rubro estimado (no sale del modelo)


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
    # Artefactos contados del modelo BIM (los IFC suelen traer los artefactos
    # aunque no las redes): informan aunque no computen costo todavía.
    sanitarios: int = 0        # inodoros, bachas, griferías, duchas...
    bocas_electricas: int = 0  # luminarias, tomas, llaves
    escaleras: int = 0
    # Fundaciones del modelo (pilotes/zapatas, a veces camuflados como
    # columnas/vigas) — computan en el rubro fundación y descuentan el estimado.
    pilotes: int = 0           # elementos tipo "pozo"
    zapatas_ml: float = 0.0    # riostras / zapatas corridas (ml)
    # Acero de armadura exacto (IfcReinforcingBar con atributos).
    armaduras: int = 0
    armadura_kg: float = 0.0
    equipos_hvac: int = 0      # calderas, calefactores
    cielorrasos: int = 0       # IfcCovering CEILING (informativo)


class SalePriceBreakdown(BaseModel):
    """Costo directo → precio de venta, paso a paso (para el waterfall)."""
    direct: float
    overhead: float      # gastos generales
    profit: float        # beneficio
    iva: float
    total: float         # precio de venta final


class ProjectBudgetSummary(BaseModel):
    plan_id: int
    project_name: str
    area_m2: float       # superficie cubierta
    area_estimated: bool = False  # True si el área es estimación (huella×pisos), no medida exacta
    materials_total: float
    labor_total: float
    labor_hours: float
    duration_days: float
    obra_gris_direct: float = 0.0   # costo directo de lo MODELADO (estructura+mampostería+aberturas)
    parametric_total: float = 0.0   # suma de rubros estimados (fundaciones, instalaciones, terminaciones)
    direct_cost: float              # obra_gris_direct + parametric_total
    sale_price: float
    cost_per_m2: float | None
    breakdown: SalePriceBreakdown
    categories: list[BudgetCategory]
    takeoff: BudgetTakeoff
