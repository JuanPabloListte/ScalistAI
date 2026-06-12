"""Test de precisión del pipeline DXF/DWG.

Verifica las garantías que vende el producto: las medidas de los elementos
son las del CAD y los overlays caen píxel-exacto sobre el render SVG.

Casos cubiertos:
- Unidades en milímetros ($INSUNITS=4): longitudes/áreas en metros reales.
- Entidad espejada (extrusión 0,0,-1): coordenadas OCS→WCS correctas.
- Muro a doble línea (dos paralelas a 15 cm): colapsa a UN elemento.
- Polilínea con bulge (muro curvo): longitud entre cuerda y arco real.
- Recinto cerrado: área (shoelace) y perímetro exactos.
- Re-encuadre al aplicar: ocultar una capa con basura lejana hace que el
  dibujo ocupe todo el lienzo, sin elementos flotando fuera del marco.
- Override de unidad ("dxf_unit" en page_scales) sobrevive al re-apply.
- El SVG de fondo lleva gid/id por capa (layer-<nombre>) para el toggle.
- Alineación: los elementos rectos tienen tinta del render debajo (±3 px).

Corre con pytest dentro del contenedor, o directo (python tests/test_dxf_import.py)
en cualquier entorno con ezdxf+matplotlib+PIL: si faltan fastapi/sqlalchemy/app
se stubean, porque acá solo se testea la lógica geométrica.
"""

import importlib.util
import json
import math
import sys
import tempfile
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _stub_missing_deps() -> None:
    """Permite importar dxf_import sin el stack completo del backend."""
    if "fastapi" not in sys.modules:
        try:
            import fastapi  # noqa: F401
        except ImportError:
            mod = types.ModuleType("fastapi")

            class HTTPException(Exception):
                def __init__(self, status_code=None, detail=None):
                    self.status_code, self.detail = status_code, detail

            mod.HTTPException = HTTPException
            sys.modules["fastapi"] = mod

    try:
        import sqlalchemy.orm  # noqa: F401
    except ImportError:
        sa = types.ModuleType("sqlalchemy")
        orm = types.ModuleType("sqlalchemy.orm")
        orm.Session = object
        sa.orm = orm
        sys.modules["sqlalchemy"] = sa
        sys.modules["sqlalchemy.orm"] = orm

    try:
        from app.core.config import settings  # noqa: F401
    except ImportError:
        app_pkg = types.ModuleType("app")
        core = types.ModuleType("app.core")
        cfg = types.ModuleType("app.core.config")
        cfg.settings = types.SimpleNamespace(STORAGE_DIR=tempfile.mkdtemp())
        models = types.ModuleType("app.models")
        de_mod = types.ModuleType("app.models.detected_element")

        class DetectedElement:
            plan_id = None
            source = None

            def __init__(self, **kw):
                self.__dict__.update(kw)

        de_mod.DetectedElement = DetectedElement
        plan_mod = types.ModuleType("app.models.plan")

        class Plan:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        plan_mod.Plan = Plan
        for name, mod in [
            ("app", app_pkg), ("app.core", core), ("app.core.config", cfg),
            ("app.models", models), ("app.models.detected_element", de_mod),
            ("app.models.plan", plan_mod),
        ]:
            sys.modules[name] = mod


def _load_dxf_import():
    _stub_missing_deps()
    spec = importlib.util.spec_from_file_location(
        "dxf_import_under_test", BACKEND_DIR / "app" / "services" / "dxf_import.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def delete(self, **k):
        return 0


class _FakeDB:
    def __init__(self):
        self.added = []

    def query(self, *a):
        return _FakeQuery()

    def add_all(self, els):
        self.added.extend(els)

    def add(self, x):
        pass

    def flush(self):
        pass


def _build_test_dxf(tmp: Path) -> Path:
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # milímetros
    for name, color in [
        ("ARQ_MURO", 7), ("CURVO", 7), ("ESPEJO", 7), ("COTAS", 1), ("RECINTOS", 3),
    ]:
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    # Muro en L: 10 m + 8 m, con DOBLE LÍNEA en el tramo de 10 m (cara a 15 cm).
    msp.add_lwpolyline([(0, 0), (10000, 0), (10000, 8000)], dxfattribs={"layer": "ARQ_MURO"})
    msp.add_line((0, 150), (10000, 150), dxfattribs={"layer": "ARQ_MURO"})
    # Muro curvo: semicírculo (bulge=1) con cuerda de 3 m (arco real π·1.5 m).
    msp.add_lwpolyline(
        [(0, -3000, 1), (3000, -3000, 0)], format="xyb", dxfattribs={"layer": "CURVO"}
    )
    # Entidad espejada: OCS x 2000..4000 con extrusión -Z → WCS x -4000..-2000.
    msp.add_lwpolyline(
        [(2000, 2000), (4000, 2000)],
        dxfattribs={"layer": "ESPEJO", "extrusion": (0, 0, -1)},
    )
    # Basura lejana que infla el encuadre hasta que se oculta la capa.
    msp.add_line((100000, 100000), (101000, 101000), dxfattribs={"layer": "COTAS"})
    # Recinto 4×5 m → área 20 m², perímetro 18 m.
    msp.add_lwpolyline(
        [(1000, 1000), (5000, 1000), (5000, 6000), (1000, 6000)],
        close=True, dxfattribs={"layer": "RECINTOS"},
    )
    out = tmp / "casa.dxf"
    doc.saveas(out)
    return out


def test_dxf_pipeline_precision():
    dxf = _load_dxf_import()
    import ezdxf
    import numpy as np
    from PIL import Image

    tmp = Path(tempfile.mkdtemp())
    dxf_file = _build_test_dxf(tmp)

    plan, _ = dxf.build_dxf_plan(1, dxf_file.read_bytes(), "casa.dxf", _FakeDB())
    if getattr(plan, "id", None) is None:
        plan.id = 1  # en producción lo asigna el flush de SQLAlchemy

    # La página inicial es el overview PNG liviano (los SVG llegan con el apply).
    png_path = Path(plan.pdf_path)
    assert png_path.suffix == ".png" and png_path.exists()

    # Override de unidad del usuario (mm confirmado) + mapeo.
    plan.page_scales = {**(plan.page_scales or {}), "dxf_unit": 0.001}
    mapping = {
        "ARQ_MURO": "wall", "CURVO": "wall", "ESPEJO": "wall",
        "COTAS": None, "RECINTOS": "room",
    }
    db = _FakeDB()
    dxf.apply_layer_mapping(plan, mapping, db)
    els = db.added
    assert els, "el mapeo no creó elementos"
    assert plan.page_scales.get("dxf_unit") == 0.001, "el apply pisó el override de unidad"
    assert plan.page_count == 1

    # Tras el apply el fondo es SVG vectorial con grupos por capa (toggle).
    svg_path = Path(plan.pdf_path)
    assert svg_path.suffix == ".svg" and svg_path.exists()
    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    assert 'id="layer-ARQ_MURO"' in svg_text, "el SVG no tiene gid por capa"

    # --- Unidades y medidas ---
    walls = [e for e in els if e.type == "wall"]
    rooms = [e for e in els if e.type == "room"]
    lens = sorted(round(e.length_m, 3) for e in walls)
    # Doble línea colapsada: UN solo muro de 10 m (no dos).
    assert sum(1 for l in lens if abs(l - 10.0) < 0.05) == 1, f"doble línea: {lens}"
    assert any(abs(l - 8.0) < 0.05 for l in lens), f"tramo de 8 m: {lens}"
    assert any(abs(l - 2.0) < 0.05 for l in lens), "falta el muro espejado de 2 m"
    # Curva: el merge de tramos casi colineales puede acortar hacia la cuerda,
    # pero el total debe quedar entre la cuerda (3 m) y el arco real (π·1.5).
    curvo = sum(l for l in lens if l < 1.9)
    assert 3.0 <= curvo <= math.pi * 1.5 + 0.05, f"curva fuera de rango: {curvo}"
    assert len(rooms) == 1
    assert abs(rooms[0].area_m2 - 20.0) < 0.01
    assert abs(rooms[0].length_m - 18.0) < 0.01

    # --- Re-encuadre: con la basura oculta, la escala es la de la casa (~14 m) ---
    assert plan.page_scales["1"] > 150, f"px/m tras re-encuadre: {plan.page_scales['1']}"

    # --- Geometría JSON-serializable ---
    for e in els:
        json.dumps(e.geometry)

    # --- Alineación contra el render (mismo marco que el apply) ---
    doc = ezdxf.readfile(dxf._source_path(plan))
    msp = doc.modelspace()
    visible = (dxf._visible_layers_default(doc) | {k for k, v in mapping.items() if v}) - {"COTAS"}
    bounds, unit, px_per_m = dxf._frame(msp, doc, visible, override_unit=0.001)
    png = tmp / "check.png"
    dxf._render_svg(doc, visible, bounds, px_per_m * unit, png, fmt="png")
    # Canal mínimo RGB: detecta líneas de cualquier color sobre blanco.
    img = np.asarray(Image.open(png).convert("RGB")).min(axis=2)
    h, w = img.shape

    for e in els:
        pts = e.geometry["points"]
        for i in range(0, len(pts), 2):
            assert 0 <= pts[i] < w and 0 <= pts[i + 1] < h, \
                f"{e.type}: punto ({pts[i]},{pts[i+1]}) fuera del marco {w}x{h}"
        # Tinta debajo: solo elementos rectos largos (los tramos de curva
        # mergeados se separan de la curva dibujada por diseño).
        if e.type == "room" or (e.length_m or 0) >= 1.9:
            mx, my = (pts[0] + pts[2]) / 2, (pts[1] + pts[3]) / 2
            win = img[max(0, int(my) - 3):int(my) + 4, max(0, int(mx) - 3):int(mx) + 4]
            assert win.size and win.min() <= 128, \
                f"{e.type} ({e.length_m} m): sin línea del render bajo ({mx:.0f},{my:.0f})"


if __name__ == "__main__":
    test_dxf_pipeline_precision()
    print("OK: test de precisión DXF completo (SVG por capas)")
