"""Dominio del simulador de escenarios.

Un `Scenario` es el cómputo de un plano bajo una **selección de recetas** (qué
receta usar por entidad constructiva). El `ScenarioCalculator` lo arma desde las
mediciones + recetas, usando `measure_for` (contrato de Fase 0) como única
fuente de medición. El `ScenarioDiff` es la resta entre dos escenarios → la
respuesta "Ladrillo vs Durlock" en $ materiales, $ mano de obra y días.

La mano de obra se separa de los materiales mirando `RecipeComponent.is_labor`
(componentes de categoría "Recursos Humanos"), para poder reportar
`labor_cost_difference` aparte de `material_cost_difference`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from app.cost_intelligence.domain.measurement import ElementGeometry, measure_for
from app.cost_intelligence.domain.value_objects import Money, Quantity

_ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class RecipeComponent:
    material_id: int
    material_name: str
    consumption: Decimal      # por unidad de la medida del elemento (m², ml, un)
    waste: Decimal
    unit_price: Money
    unit: str = "un"          # unidad del material (un, bolsa, m3, hs...)
    is_labor: bool = False    # True si es mano de obra (categoría Recursos Humanos)


@dataclass(frozen=True, slots=True)
class Recipe:
    id: int
    name: str
    entity_type: str          # = applies_to ("wall", "roof"...)
    daily_yield: Decimal      # medida por día (para la duración)
    components: tuple[RecipeComponent, ...]


@dataclass(frozen=True, slots=True)
class ElementMeasurement:
    entity_type: str
    geometry: ElementGeometry
    recipe_id: Optional[int] = None  # receta asignada a ESTE elemento (override del default por tipo)


@dataclass(frozen=True, slots=True)
class MaterialLine:
    material_id: int
    material_name: str
    quantity: Quantity
    unit_cost: Money
    total: Money


@dataclass(frozen=True, slots=True)
class ScenarioTotals:
    materials: Money
    labor_cost: Money
    labor_hours: Decimal
    duration_days: Decimal


@dataclass(frozen=True, slots=True)
class Scenario:
    label: str
    totals: ScenarioTotals
    lines: tuple[MaterialLine, ...]


@dataclass(frozen=True, slots=True)
class ScenarioDiff:
    base_label: str
    alt_label: str
    material_cost_difference: Money   # alt − base
    labor_cost_difference: Money      # alt − base
    time_saved_days: Decimal          # base − alt (positivo = la alternativa ahorra)

    @classmethod
    def between(cls, base: Scenario, alt: Scenario) -> "ScenarioDiff":
        return cls(
            base_label=base.label,
            alt_label=alt.label,
            material_cost_difference=(alt.totals.materials - base.totals.materials),
            labor_cost_difference=(alt.totals.labor_cost - base.totals.labor_cost),
            time_saved_days=(base.totals.duration_days - alt.totals.duration_days),
        )


class ScenarioCalculator:
    """Computa un `Scenario` desde mediciones + receta elegida por entidad."""

    def calculate(
        self,
        label: str,
        measurements: Iterable[ElementMeasurement],
        recipe_by_entity: dict[str, Recipe],
        override_recipes: Optional[dict[int, Recipe]] = None,
        currency: str = "ARS",
    ) -> Scenario:
        materials = Money.zero(currency)
        labor_cost = Money.zero(currency)
        labor_hours = Decimal("0")
        duration_days = Decimal("0")
        # material_id -> [name, qty_acumulada, unit_price, unit]
        lines: dict[int, list] = {}

        for m in measurements:
            # Receta ASIGNADA a este elemento (override) o la default del tipo.
            recipe = None
            if m.recipe_id is not None and override_recipes:
                recipe = override_recipes.get(m.recipe_id)
            if recipe is None:
                recipe = recipe_by_entity.get(m.entity_type)
            if recipe is None:
                continue
            measured = measure_for(m.entity_type, m.geometry)
            if measured is None:
                continue
            base_qty = measured.value  # Decimal

            if recipe.daily_yield and recipe.daily_yield > 0:
                duration_days += base_qty / recipe.daily_yield

            for c in recipe.components:
                qty = base_qty * c.consumption * (_ONE + c.waste)
                cost = c.unit_price * qty
                if c.is_labor:
                    labor_cost = labor_cost + cost
                    if c.unit.lower() == "hs":
                        labor_hours += qty
                else:
                    materials = materials + cost
                    if c.material_id in lines:
                        lines[c.material_id][1] += qty
                    else:
                        lines[c.material_id] = [c.material_name, qty, c.unit_price, c.unit or "un"]

        material_lines = tuple(
            MaterialLine(
                material_id=mid,
                material_name=name,
                quantity=Quantity(qty, unit),
                unit_cost=price,
                total=(price * qty).rounded(),
            )
            for mid, (name, qty, price, unit) in sorted(lines.items())
        )
        totals = ScenarioTotals(
            materials=materials.rounded(),
            labor_cost=labor_cost.rounded(),
            labor_hours=labor_hours,
            duration_days=duration_days,
        )
        return Scenario(label=label, totals=totals, lines=material_lines)
