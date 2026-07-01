"""Tests del import vectorial de PDF y de la detección de escala.

Cubre la lógica que decide QUÉ se extrae de un PDF con capas CAD:
- _classify_layer: keywords ES/EN, exclusiones (pluvial≠cloaca, hatches del
  plotter), prioridad riostra>beam, fallback LLM vía `extra`.
- _page_allowed_types: gate de disciplina por rótulo (una lámina de cloacas
  no aporta muros aunque la arquitectura esté de fondo como xref).
- page_scale_pt_per_m: escala desde cotas (texto "3.50" junto a su línea de
  cota) con mediana + validación de consistencia; rechaza cotas inconsistentes.
- auto_scale._find_denominator: regex de rótulo "ESC 1:100" y variantes.

El PDF de prueba se fabrica con PyMuPDF (capas OCG reales + texto), sin
depender de archivos binarios en el repo.

Corre directo: python tests/test_pdf_vector_import.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load(module_filename: str, alias: str):
    spec = importlib.util.spec_from_file_location(
        alias, BACKEND_DIR / "app" / "services" / module_filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- capas

def test_classify_layer_keywords():
    pv = _load("pdf_vector_import.py", "pv_under_test")
    cases = {
        "ARQ-MUROS EXTERIORES": "wall",
        "Tabiquería interior": "wall",
        "A-CARPINTERIAS": "opening",
        "VENTANAS PB": "opening",
        "DESAGUE CLOACAL PB": "cloaca",
        "IE-BOCAS DE TECHO": "electricidad",
        "S-COL HormigonArmado": "column",
        "VIGAS DE FUNDACION": "riostra",   # riostra ANTES que beam
        "-V0 VIGAS": "beam",               # convención "-V0" del estudio
        "ESCALERA PRINCIPAL": "escalera",
        "ZAPATAS AISLADAS": "pozo",
        "DESAGUE PLUVIAL": None,           # pluvial NO es cloaca
        "PDF32_HATCH": None,               # basura del plotter
        "LAYER_37": None,                  # críptica: sin keyword no clasifica
    }
    for name, expected in cases.items():
        got = pv._classify_layer(name)
        assert got == expected, f"{name!r}: esperaba {expected}, dio {got}"

    # Fallback semántico (mapa LLM precalculado) para capas crípticas.
    assert pv._classify_layer("LAYER_37", extra={"LAYER_37": "wall"}) == "wall"


def test_page_allowed_types_por_rotulo():
    pv = _load("pdf_vector_import.py", "pv_under_test2")
    import fitz

    def _page_with(text: str):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return page

    arch = pv._page_allowed_types(_page_with("PLANTA DE ARQUITECTURA PB"))
    assert "wall" in arch and "opening" in arch and "cloaca" not in arch

    cloaca = pv._page_allowed_types(_page_with("INSTALACION CLOACAL PLANTA BAJA"))
    assert cloaca == {"cloaca"}, f"lámina de cloacas: {cloaca}"

    # Lámina combinada: aporta ambas disciplinas.
    combo = pv._page_allowed_types(
        _page_with("PLANTA GENERAL E INSTALACION ELECTRICA Y SANITARIA")
    )
    assert "electricidad" in combo and "cloaca" in combo

    # Planilla/detalle sin rótulo de disciplina: no aporta nada.
    assert pv._page_allowed_types(_page_with("PLANILLA DE LOCALES")) == set()


# ---------------------------------------------------------------- escala

def _make_cota_pdf(tmp: Path, pt_per_m: float, *, inconsistent: bool = False) -> Path:
    """PDF con capa OCG 'COTAS': líneas horizontales con su texto de medida.

    Cada cota mide `valor × pt_per_m` puntos. Con inconsistent=True, la mitad
    usa otra escala → la validación de consistencia debe rechazar la página.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 apaisado
    ocg = doc.add_ocg("COTAS")
    values = [3.50, 2.00, 5.00, 4.25, 1.50, 2.75]
    y = 80.0
    for i, v in enumerate(values):
        scale = pt_per_m * (1.6 if inconsistent and i % 2 else 1.0)
        x0 = 60.0
        x1 = x0 + v * scale
        page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), oc=ocg, width=0.5)
        # Texto centrado sobre la línea (a <18 pt del punto medio).
        page.insert_text(fitz.Point((x0 + x1) / 2 - 8, y - 4), f"{v:.2f}", fontsize=6)
        y += 60.0
    out = tmp / ("cotas_mal.pdf" if inconsistent else "cotas.pdf")
    doc.save(out)
    return out


def test_page_scale_desde_cotas():
    pv = _load("pdf_vector_import.py", "pv_under_test3")
    import fitz

    tmp = Path(tempfile.mkdtemp())
    pdf = _make_cota_pdf(tmp, pt_per_m=20.0)
    page = fitz.open(pdf)[0]
    got = pv.page_scale_pt_per_m(page)
    assert got is not None, "no detectó escala con 6 cotas consistentes"
    assert abs(got - 20.0) / 20.0 < 0.02, f"pt/m: esperaba 20, dio {got}"


def test_page_scale_rechaza_cotas_inconsistentes():
    pv = _load("pdf_vector_import.py", "pv_under_test4")
    import fitz

    tmp = Path(tempfile.mkdtemp())
    pdf = _make_cota_pdf(tmp, pt_per_m=20.0, inconsistent=True)
    page = fitz.open(pdf)[0]
    assert pv.page_scale_pt_per_m(page) is None, \
        "aceptó una página con cotas a dos escalas distintas (debería desconfiar)"


def test_find_denominator_rotulo():
    asc = _load("auto_scale.py", "auto_scale_under_test")
    cases = {
        "ESCALA: 1:100": 100.0,
        "Esc. 1/75": 75.0,
        "ESC 1:50": 50.0,
        "escala 1 : 25": 25.0,
        "ESCALA GRAFICA": None,          # sin ratio
        "PLANO 11/2024": None,           # fecha, no escala (sin keyword pegada)
    }
    for text, expected in cases.items():
        got = asc._find_denominator(text)
        assert got == expected, f"{text!r}: esperaba {expected}, dio {got}"


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
