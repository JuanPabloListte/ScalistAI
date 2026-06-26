"""Contrato de medición: cómo cada tipo de elemento del CAD se traduce a la
medida que consume una receta (m², ml o m² de sección).

Hoy este criterio está **duplicado** en `_export.py` (`_get_materials_summary_data`)
y en `schedule.py` (`_area_for_cost`, `_qty_for_duration`, `_unit_for`). Acá
vive UNA sola vez como fuente de verdad del dominio; los motores lo consumirán
por la capa de aplicación (paso posterior, con tests de regresión).

Nota de diseño — el "quirk" de columnas/pozos: el motor actual mide columna y
pozo por su **área de sección** (`area_m2`) sin multiplicar por la altura. Se
preserva ese comportamiento acá (para NO cambiar presupuestos existentes) pero
queda marcado: corregirlo a volumen (sección × altura) es un cambio aparte con
regresión. Ver docs/cost-intelligence/README.md (riesgo "correctitud dimensional").
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.cost_intelligence.domain.value_objects import Quantity

# Altura por defecto cuando el CAD no la trae (muros y aberturas).
_DEFAULT_HEIGHT_M = Decimal("2.8")
_DEFAULT_OPENING_HEIGHT_M = Decimal("2.1")


@dataclass(frozen=True, slots=True)
class ElementGeometry:
    """Geometría mínima de un DetectedElement, en unidades reales (metros).
    Es el VO de entrada del contrato; la capa anti-corrupción lo arma desde el
    modelo ORM."""

    length_m: Optional[float] = None
    area_m2: Optional[float] = None
    height_m: Optional[float] = None


# applies_to -> (criterio, unidad). Criterios:
#   "area"         -> area_m2 directa (piso/techo/escalera/columna-sección/pozo)
#   "length"       -> length_m (viga/riostra/cloaca/electricidad/perímetro)
#   "wall_area"    -> length_m × height_m (muro)
#   "opening_area" -> length_m × height_m con altura de abertura
_BASIS: dict[str, tuple[str, str]] = {
    "wall": ("wall_area", "m2"),
    "room_floor": ("area", "m2"),
    "roof": ("area", "m2"),
    "escalera": ("area", "m2"),
    "room_wall": ("wall_area", "m2"),
    "room_perimeter": ("length", "ml"),
    "opening": ("opening_area", "m2"),
    "opening_perimeter": ("length", "ml"),
    "beam": ("length", "ml"),
    "riostra": ("length", "ml"),
    "cloaca": ("length", "ml"),
    "electricidad": ("length", "ml"),
    "column": ("area", "m2"),   # sección (quirk: sin altura) — ver módulo docstring
    "pozo": ("area", "m2"),     # ídem
}


def unit_for(applies_to: str) -> Optional[str]:
    """Unidad de la medida de esa receta, o None si el tipo no se reconoce."""
    basis = _BASIS.get(applies_to)
    return basis[1] if basis else None


def measure_for(applies_to: str, geom: ElementGeometry) -> Optional[Quantity]:
    """Medida que la receta `applies_to` consume de este elemento.

    Devuelve None si el tipo no aplica o falta la geometría necesaria. Es el
    ÚNICO lugar donde vive el criterio por tipo (DRY + correctitud)."""
    basis = _BASIS.get(applies_to)
    if basis is None:
        return None
    kind, unit = basis

    def dec(v: Optional[float]) -> Optional[Decimal]:
        return Decimal(str(v)) if v is not None else None

    if kind == "area":
        a = dec(geom.area_m2)
        return Quantity(a, unit) if a and a > 0 else None
    if kind == "length":
        length = dec(geom.length_m)
        return Quantity(length, unit) if length and length > 0 else None
    if kind in ("wall_area", "opening_area"):
        length = dec(geom.length_m)
        if not length or length <= 0:
            return None
        default = _DEFAULT_OPENING_HEIGHT_M if kind == "opening_area" else _DEFAULT_HEIGHT_M
        height = dec(geom.height_m) or default
        return Quantity(length * height, unit)
    return None
