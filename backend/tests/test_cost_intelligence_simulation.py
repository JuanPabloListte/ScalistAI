"""Tests de Fase 2b: el serializador `scenario_payload` (Scenario → JSON), que
es lo que persiste el read-model `simulations`. Puro, sin DB.

(La persistencia SQL y los endpoints HTTP se validaron por smoke end-to-end
sobre plan real; un test HTTP completo requiere fixtures de auth.)

Corre directo:  python tests/test_cost_intelligence_simulation.py
"""
import sys
from decimal import Decimal as D
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.domain.measurement import ElementGeometry  # noqa: E402
from app.cost_intelligence.domain.scenario import (  # noqa: E402
    ElementMeasurement, Recipe, RecipeComponent, ScenarioCalculator,
)
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402
from app.cost_intelligence.infrastructure.persistence.simulation_store import scenario_payload  # noqa: E402


def _scenario():
    recipe = Recipe(7, "Muro", "wall", D(10), (
        RecipeComponent(1, "Ladrillo", D(1), D(0), Money(100), "un", False),
        RecipeComponent(99, "Mano de Obra", D(2), D(0), Money(50), "hs", True),
    ))
    measurements = [ElementMeasurement("wall", ElementGeometry(length_m=10.0, height_m=1.0))]
    return ScenarioCalculator().calculate("Base", measurements, {"wall": recipe})


def test_payload_totals_are_json_safe_floats():
    totals, _ = scenario_payload(_scenario())
    assert totals == {"materials": 1000.0, "labor_cost": 1000.0,
                      "labor_hours": 20.0, "duration_days": 1.0}
    assert all(isinstance(v, float) for v in totals.values())


def test_payload_lines():
    _, lines = scenario_payload(_scenario())
    assert len(lines) == 1  # la mano de obra no es línea de material
    ln = lines[0]
    assert ln["material_id"] == 1 and ln["material_name"] == "Ladrillo"
    assert ln["quantity"] == 10.0 and ln["unit"] == "un" and ln["total"] == 1000.0
    assert all(isinstance(ln[k], float) for k in ("quantity", "unit_cost", "total"))


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
