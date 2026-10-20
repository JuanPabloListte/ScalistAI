"""Presupuesto por rubros en PDF (services/budget_pdf.py). Sin DB.

Corre directo: python tests/test_budget_pdf.py (dentro del contenedor).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _view():
    from app.services.budget_rules import compute_price

    budget = {
        "items": [
            {"status": "ok", "label": "Ladrillo", "stage": "Mampostería", "unit": "u",
             "quantity": 1000, "subtotal": 1_000_000},
            {"status": "ok", "label": "Cemento (hormigón)", "stage": "Estructura", "unit": "kg",
             "quantity": 500, "subtotal": 300_000},
            {"status": "sin_precio", "label": "Piedra", "stage": "Estructura", "unit": "m3",
             "quantity": 2, "subtotal": None},
        ],
        # Comprar unidades enteras suma $ 20.000 a lo que consumen las reglas.
        "totals": {"net": 1_320_000, "iva": 0, "total": 0, "iva_rate": 0.21},
        "counts": {"ok": 2, "sin_precio": 1, "sin_medida": 0},
    }
    labor = {
        "items": [{"status": "ok", "label": "Mano de obra: mampostería", "stage": "Mampostería",
                   "measure_unit": "m2", "quantity": 100, "unit_price": 5000, "cost": 500_000}],
        "total": 500_000, "counts": {"ok": 1, "pendientes": 0, "sin_medida": 0},
    }
    price = compute_price(1_320_000, 500_000, overhead_pct=0.15, profit_pct=0.10)
    return {"budget": budget, "labor": labor, "price": price,
            "measures": {"measures": [{"key": "sup_cubierta_m2", "value": 120}]}}


def _text(pdf: bytes) -> str:
    import fitz

    return "\n".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))


def _money(n: float) -> str:
    return "$ " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def test_comitente_reparte_margenes_y_cierra_con_el_total():
    from app.services.budget_pdf import build_budget_pdf

    v = _view()
    txt = _text(build_budget_pdf({"id": 7, "name": "Casa Test", "address": "Calle 1"},
                                 {"name": "Estudio Test", "contact_info": "Tel. 0000"}, v))
    assert "Presupuesto Nº 0007" in txt and "Estudio Test" in txt and "Tel. 0000" in txt
    assert "Gastos generales" not in txt and "Beneficio" not in txt  # no muestra el margen
    assert _money(v["price"]["net"]) in txt and _money(v["price"]["total"]) in txt
    # Los rubros del resumen suman el precio sin IVA.
    k = v["price"]["net"] / 1_800_000
    mamp = round(1_500_000 * k, 2)
    assert _money(mamp) in txt, txt
    assert _money(round(v["price"]["net"] - mamp, 2)) in txt
    assert "Piedra" not in txt  # sin precio: no entra


def test_interno_muestra_costos_redondeo_y_margenes():
    from app.services.budget_pdf import build_budget_pdf

    v = _view()
    txt = _text(build_budget_pdf({"id": 7, "name": "Casa Test", "address": None},
                                 {"name": "Estudio Test"}, v, "interno"))
    assert "uso interno" in txt
    assert "Redondeo a unidades de venta" in txt and _money(20_000) in txt
    for key in ("direct", "overhead", "profit", "net", "iva", "total"):
        assert _money(v["price"][key]) in txt, key
    assert re.search(r"1 ítems sin precio", txt)


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {str(exc)[:300]}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
