"""Caso de uso: comparar dos recetas alternativas de una misma entidad.

Computa el escenario con la receta A y con la receta B (todo lo demás igual, con
las defaults), y devuelve el `ScenarioDiff` → diferencia en $ materiales, $ mano
de obra y días. Es la respuesta "Ladrillo vs Durlock".
"""
from __future__ import annotations

from typing import Optional

from app.cost_intelligence.application.scenario_ports import RecipeCatalog
from app.cost_intelligence.application.use_cases.run_simulation import RunSimulation
from app.cost_intelligence.domain.scenario import Scenario, ScenarioDiff


class CompareScenarios:
    def __init__(self, run_simulation: RunSimulation, catalog: RecipeCatalog) -> None:
        self._run = run_simulation
        self._catalog = catalog

    def execute(
        self,
        plan_id: int,
        organization_id: int,
        entity_type: str,
        recipe_a_id: int,
        recipe_b_id: int,
        *,
        page: Optional[int] = None,
    ) -> tuple[Scenario, Scenario, ScenarioDiff]:
        recipe_a = self._catalog.recipe(recipe_a_id)
        recipe_b = self._catalog.recipe(recipe_b_id)
        if recipe_a is None or recipe_b is None:
            raise ValueError("Receta A o B inexistente")
        if recipe_a.entity_type != entity_type or recipe_b.entity_type != entity_type:
            raise ValueError("Ambas recetas deben ser de la misma entidad que se compara")

        scenario_a = self._run.execute(
            plan_id, organization_id, {entity_type: recipe_a_id}, label=recipe_a.name, page=page,
        )
        scenario_b = self._run.execute(
            plan_id, organization_id, {entity_type: recipe_b_id}, label=recipe_b.name, page=page,
        )
        return scenario_a, scenario_b, ScenarioDiff.between(scenario_a, scenario_b)
