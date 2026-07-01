"""Caso de uso: correr la simulación de un plano (presupuesto base o con una
selección de recetas).

Para cada entidad presente en el plano usa la receta elegida (`selection`) o, si
no se especifica, la default de la org. Devuelve un `Scenario` con totales y
líneas de material.
"""
from __future__ import annotations

from typing import Optional

from app.cost_intelligence.application.scenario_ports import MeasurementProvider, RecipeCatalog
from app.cost_intelligence.domain.scenario import Scenario, ScenarioCalculator


class RunSimulation:
    def __init__(
        self,
        measurements: MeasurementProvider,
        catalog: RecipeCatalog,
        calculator: Optional[ScenarioCalculator] = None,
    ) -> None:
        self._measurements = measurements
        self._catalog = catalog
        self._calculator = calculator or ScenarioCalculator()

    def execute(
        self,
        plan_id: int,
        organization_id: int,
        selection: Optional[dict[str, int]] = None,
        *,
        label: str = "Base",
        page: Optional[int] = None,
    ) -> Scenario:
        selection = selection or {}
        measurements = self._measurements.measurements_for(plan_id, page)

        recipe_by_entity = {}
        for entity_type in {m.entity_type for m in measurements}:
            chosen_id = selection.get(entity_type)
            recipe = (
                self._catalog.recipe(chosen_id) if chosen_id is not None
                else self._catalog.default_recipe(organization_id, entity_type)
            )
            if recipe is not None:
                recipe_by_entity[entity_type] = recipe

        # Recetas asignadas a elementos puntuales (override del default por tipo):
        # así "esta pared piedra, esta ladrillo" computa bien, no una sola por tipo.
        override_recipes = {}
        for rid in {m.recipe_id for m in measurements if m.recipe_id is not None}:
            recipe = self._catalog.recipe(rid)
            if recipe is not None:
                override_recipes[rid] = recipe

        return self._calculator.calculate(label, measurements, recipe_by_entity, override_recipes)
