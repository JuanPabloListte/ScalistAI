"""Tests de Fase 2a: el núcleo del simulador (ScenarioCalculator + casos de uso)
con providers FAKE in-memory (sin DB). Verifica el cómputo, el diff
Ladrillo-vs-Durlock y que se use `measure_for` por tipo de entidad.

Corre directo:  python tests/test_cost_intelligence_scenario.py
"""
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.application.scenario_ports import (  # noqa: E402
    MeasurementProvider, RecipeCatalog,
)
from app.cost_intelligence.application.use_cases.compare_scenarios import CompareScenarios  # noqa: E402
from app.cost_intelligence.application.use_cases.run_simulation import RunSimulation  # noqa: E402
from app.cost_intelligence.domain.measurement import ElementGeometry  # noqa: E402
from app.cost_intelligence.domain.scenario import (  # noqa: E402
    ElementMeasurement, Recipe, RecipeComponent,
)
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402

D = Decimal

# Receta A "Ladrillo": material $100 (1/m²) + mano de obra $50 (2 hs/m²); 10 m²/día
RECIPE_A = Recipe(7, "Muro Ladrillo", "wall", D(10), (
    RecipeComponent(1, "Ladrillo", D(1), D(0), Money(100), "un", False),
    RecipeComponent(99, "Mano de Obra", D(2), D(0), Money(50), "hs", True),
))
# Receta B "Durlock": material $80 (1/m²) + mano de obra $50 (1 hs/m²); 20 m²/día (más rápido)
RECIPE_B = Recipe(12, "Muro Durlock", "wall", D(20), (
    RecipeComponent(2, "Placa Durlock", D(1), D(0), Money(80), "un", False),
    RecipeComponent(99, "Mano de Obra", D(1), D(0), Money(50), "hs", True),
))
# Receta de viga (lineal, ml) para verificar measure_for por tipo
RECIPE_BEAM = Recipe(20, "Viga H°A°", "beam", D(30), (
    RecipeComponent(3, "Hormigón", D(2), D(0), Money(1000), "m3", False),
))


class FakeMeasurements(MeasurementProvider):
    def __init__(self, items: list[ElementMeasurement]) -> None:
        self._items = items

    def measurements_for(self, plan_id: int, page: Optional[int] = None) -> list[ElementMeasurement]:
        return list(self._items)


class FakeCatalog(RecipeCatalog):
    def __init__(self, recipes: dict[int, Recipe], defaults: dict[str, Recipe]) -> None:
        self._recipes = recipes
        self._defaults = defaults

    def recipe(self, recipe_id: int) -> Optional[Recipe]:
        return self._recipes.get(recipe_id)

    def default_recipe(self, organization_id: int, entity_type: str) -> Optional[Recipe]:
        return self._defaults.get(entity_type)


# 1 muro de 10 m² (length 10 × height 1)
WALL_10M2 = [ElementMeasurement("wall", ElementGeometry(length_m=10.0, height_m=1.0))]


def _run_uc(measurements):
    catalog = FakeCatalog({7: RECIPE_A, 12: RECIPE_B, 20: RECIPE_BEAM}, {"wall": RECIPE_A})
    return RunSimulation(FakeMeasurements(measurements), catalog), catalog


def test_base_totals_separates_materials_and_labor():
    run, _ = _run_uc(WALL_10M2)
    s = run.execute(plan_id=1, organization_id=1, selection={"wall": 7})
    assert s.totals.materials.amount == D("1000")     # 10 × 1 × 100
    assert s.totals.labor_cost.amount == D("1000")    # 10 × 2 × 50
    assert s.totals.labor_hours == D("20")            # 10 × 2
    assert s.totals.duration_days == D("1")           # 10 / 10


def test_default_recipe_used_when_no_selection():
    run, _ = _run_uc(WALL_10M2)
    s = run.execute(plan_id=1, organization_id=1)  # sin selección → default = A
    assert s.totals.materials.amount == D("1000")
    assert s.label == "Base"


def test_material_lines():
    run, _ = _run_uc(WALL_10M2)
    s = run.execute(plan_id=1, organization_id=1, selection={"wall": 7})
    assert len(s.lines) == 1  # solo material, la MO no es línea de material
    line = s.lines[0]
    assert line.material_id == 1 and line.quantity.value == D("10") and line.total.amount == D("1000")


def test_compare_durlock_cheaper_and_faster():
    run, catalog = _run_uc(WALL_10M2)
    _, _, diff = CompareScenarios(run, catalog).execute(1, 1, "wall", recipe_a_id=7, recipe_b_id=12)
    assert diff.material_cost_difference.amount == D("-200")  # 800 − 1000
    assert diff.labor_cost_difference.amount == D("-500")     # 500 − 1000
    assert diff.time_saved_days == D("0.5")                   # 1 − 0.5
    assert diff.alt_label == "Muro Durlock"


def test_compare_rejects_mismatched_entity():
    run, catalog = _run_uc(WALL_10M2)
    try:
        CompareScenarios(run, catalog).execute(1, 1, "wall", recipe_a_id=7, recipe_b_id=20)  # 20 es beam
        assert False, "comparar recetas de distinta entidad debería fallar"
    except ValueError:
        pass


def test_measure_for_applies_per_type():
    # Una viga de 5 ml: la medida debe ser longitud (ml), no área.
    beam = [ElementMeasurement("beam", ElementGeometry(length_m=5.0))]
    catalog = FakeCatalog({20: RECIPE_BEAM}, {"beam": RECIPE_BEAM})
    s = RunSimulation(FakeMeasurements(beam), catalog).execute(1, 1)
    assert s.totals.materials.amount == D("10000")  # 5 ml × 2 m3/ml × $1000


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests pasaron")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
