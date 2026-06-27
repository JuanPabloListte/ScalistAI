"""Tests de Fase 5: el `build_workbook` genera un XLSX válido de 4 hojas.
Reabre el archivo con openpyxl y verifica estructura + valores. Sin DB.

Corre directo:  python tests/test_cost_intelligence_export.py
"""
import sys
from io import BytesIO
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from openpyxl import load_workbook  # noqa: E402

from app.cost_intelligence.infrastructure.export.xlsx_exporter import build_workbook  # noqa: E402

SIM = {
    "name": "Presupuesto Test",
    "totals": {"materials": 1000.0, "labor_cost": 500.0, "labor_hours": 20.0, "duration_days": 2.0},
    "lines": [{"material_name": "Ladrillo", "quantity": 160.0, "unit": "un", "unit_cost": 6.25, "total": 1000.0}],
}
SCEN = [{"entity": "Muro", "base": "Ladrillo", "alternative": "Durlock",
         "material_diff": -200.0, "labor_diff": -100.0, "time_saved": 1.5}]
PROJ = [{"horizon_months": 6, "projected_cost": 1800.0, "variation": 20.0}]


def _wb(scen=SCEN, proj=PROJ):
    return load_workbook(BytesIO(build_workbook(SIM, scen, proj)))


def test_produces_valid_xlsx_with_4_sheets():
    data = build_workbook(SIM, SCEN, PROJ)
    assert isinstance(data, bytes) and len(data) > 0
    assert _wb().sheetnames == ["Presupuesto", "Escenarios", "Proyección", "Detalle materiales"]


def test_presupuesto_total_obra():
    ws = _wb()["Presupuesto"]
    vals = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, ws.max_row + 1)}
    assert vals.get("Materiales") == 1000.0
    assert vals.get("TOTAL OBRA") == 1500.0  # materiales + MO


def test_detalle_lista_material():
    ws = _wb()["Detalle materiales"]
    assert any(ws.cell(r, 1).value == "Ladrillo" for r in range(1, ws.max_row + 1))


def test_escenarios_muestra_diff():
    ws = _wb()["Escenarios"]
    found = False
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 3).value == "Durlock":
            assert ws.cell(r, 4).value == -200.0
            found = True
    assert found


def test_hojas_vacias_no_rompen():
    wb = _wb(scen=[], proj=[])
    assert "Escenarios" in wb.sheetnames and "Proyección" in wb.sheetnames


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
