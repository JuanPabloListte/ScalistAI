"""Importación de planos DXF / DWG.

El archivo CAD se plotea a un PDF vectorial con estilo "plano impreso"
(fondo blanco, líneas oscuras, colores de capa conservados) usando el
add-on drawing de ezdxf. El frontend mapea capas → tipos de elemento y el
backend crea los DetectedElement con la geometría matemática exacta del
CAD, sin pasar por la IA.

Decisiones de precisión (no simplificar sin entender):
- Toda la geometría se extrae en WCS vía ezdxf.path.make_path(), que aplica
  la transformación OCS (entidades con extrusión / espejadas) y resuelve
  bulges, arcos, elipses y splines. Leer entity.dxf.* a mano da coordenadas
  OCS crudas y desparrama los elementos por cualquier lado.
- El encuadre (bounds) sale de ezdxf.bbox.extents() sobre las MISMAS
  entidades visibles que dibuja el render: un solo marco para PDF y px.
- Las unidades del dibujo se detectan con $INSUNITS + heurística por tamaño
  y todo lo métrico (length_m, area_m2, px/m) se convierte a metros reales.
- Al aplicar el mapeo se re-encuadra usando solo las capas visibles, se
  re-renderiza el PDF y se recalcula la escala; los elementos source="dxf"
  se regeneran siempre con ese mismo marco.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional

import ezdxf
import ezdxf.colors as dxfcolors
from ezdxf import bbox as ezbbox
from ezdxf import path as ezpath
from fastapi import HTTPException
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.detected_element import DetectedElement
from app.models.plan import Plan

# Palabras clave para sugerir tipo automáticamente a partir del nombre de capa.
_LAYER_SUGGESTIONS: list[tuple[tuple[str, ...], str]] = [
    (("MURO", "WALL", "PARED"),                   "wall"),
    (("PUERTA", "DOOR"),                           "opening"),
    (("VENTANA", "WINDOW"),                        "opening"),
    (("ABERTURA", "CARPINTERIA"),                  "opening"),
    (("HABITACION", "ROOM", "RECINTO", "CUARTO"),  "room"),
    (("VIGA", "BEAM"),                             "beam"),
    (("COLUMNA", "COLUMN", "PILAR"),               "column"),
    (("LOSA", "TECHO", "ROOF", "SLAB", "CUBIERTA"),"roof"),
    (("CLOACA", "CLOACAL", "SANITARI", "DESAGUE"), "cloaca"),
    (("ELECTRIC", "ILUMINAC", "TOMA", "TABLERO"),  "electricidad"),
    (("ESCALERA", "STAIR"),                        "escalera"),
    (("RIOSTRA", "ENCADENADO", "FUNDACION", "ZAPATA"), "riostra"),
]

# Valor especial del mapeo: la capa se ve en el fondo pero no genera elementos.
CONTEXT_TYPE = "context"

# Contrato de geometry.points con el visor (plan-viewer-inner.tsx):
#   segmento  [x1,y1,x2,y2]             → wall, opening, beam, riostra
#   polígono  [x1,y1,...] (≥3 puntos)   → room, roof, column
#   polilínea [x1,y1,...] (≥2 puntos)   → cloaca, electricidad
_SEGMENT_TYPES = {"wall", "opening", "beam", "riostra"}
_POLYGON_TYPES = {"room", "roof", "column", "escalera"}
_PATH_TYPES = {"cloaca", "electricidad"}


def _suggest_type(layer_name: str) -> Optional[str]:
    up = layer_name.upper()
    for keywords, el_type in _LAYER_SUGGESTIONS:
        if any(k in up for k in keywords):
            return el_type
    return None

_TARGET_MAX_PX = 3000
_MAX_IMG_PX    = 4000
_MIN_PX_PER_M  = 20.0
_MAX_PX_PER_M  = 300.0
_MARGIN_PX     = 60
_MIN_ELEMENT_PX = 5.0  # entidades más chicas que esto se descartan como ruido

# Tolerancias en METROS reales (se dividen por el factor de unidad al usarlas
# sobre coordenadas crudas del dibujo).
_FLATTEN_M  = 0.01  # error máximo al aplanar curvas
_SIMPLIFY_M = 0.02  # desviación máxima al simplificar polilíneas (Douglas-Peucker)

# $INSUNITS → factor a metros. Solo unidades plausibles para planos.
_INSUNITS_TO_M = {
    1: 0.0254,   # pulgadas
    2: 0.3048,   # pies
    4: 0.001,    # milímetros
    5: 0.01,     # centímetros
    6: 1.0,      # metros
    14: 0.1,     # decímetros
}


# ---------------------------------------------------------------------------
# Unidades
# ---------------------------------------------------------------------------

def _detect_unit_scale(doc, span_raw: float) -> float:
    """Factor unidad-de-dibujo → metros.

    Confía en $INSUNITS solo si el tamaño resultante es plausible para un
    plano (0.5 m – 5 km); si no, heurística por magnitud: los planos de
    arquitectura miden decenas de metros, así que un dibujo de miles de
    unidades está en mm y uno de cientos en cm.
    """
    try:
        ins = int(doc.header.get("$INSUNITS", 0))
    except Exception:
        ins = 0
    factor = _INSUNITS_TO_M.get(ins)
    if factor is not None and 0.5 <= span_raw * factor <= 5000:
        return factor
    # Sin $INSUNITS confiable: probar m → cm → mm y quedarse con el primero
    # que deje la lámina en rango de plano típico (20–600 m; las láminas
    # tienen vistas dispersas, por eso el techo es generoso). Metros primero:
    # es lo más común en arquitectura de habla hispana.
    for f in (1.0, 0.01, 0.001):
        if 20 <= span_raw * f <= 600:
            return f
    if span_raw > 8000:
        return 0.001
    if span_raw > 400:
        return 0.01
    return 1.0


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------

def _aci_to_paper_rgb(aci: int) -> tuple[int, int, int]:
    """ACI index → RGB apto para fondo blanco.
    ACI 7 es "blanco" en pantalla negra → se convierte a negro de papel."""
    if aci == 7:
        return (15, 15, 15)
    try:
        r, g, b = dxfcolors.aci2rgb(aci)
    except Exception:
        return (80, 80, 80)
    # Colores muy claros (invisibles en blanco) los oscurecemos.
    if r + g + b > 640:
        return (int(r * 0.45), int(g * 0.45), int(b * 0.45))
    return (r, g, b)


# ---------------------------------------------------------------------------
# Geometría WCS
# ---------------------------------------------------------------------------

_PATHABLE = {
    "LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE",
    "ELLIPSE", "SPLINE", "SOLID", "TRACE", "3DFACE",
}


def _entity_wcs_points(entity, flat_dist: float) -> Optional[list[tuple[float, float]]]:
    """Puntos (x, y) en WCS de una entidad geométrica, o None.

    make_path aplica la transformación OCS→WCS (extrusiones/espejados) y
    aplana bulges, arcos y splines con error máximo `flat_dist` (en unidades
    del dibujo). Entidades no geométricas (textos, cotas) devuelven None.
    """
    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(s.x, s.y), (e.x, e.y)]

    if kind == "HATCH":
        try:
            pts: list[tuple[float, float]] = []
            for p in ezpath.from_hatch(entity):
                pts.extend((v.x, v.y) for v in p.flattening(flat_dist))
            return pts or None
        except Exception:
            return None

    if kind in _PATHABLE:
        try:
            p = ezpath.make_path(entity)
            pts = [(v.x, v.y) for v in p.flattening(flat_dist)]
            return pts or None
        except Exception:
            return None

    return None


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo: colapsa los puntos del aplanado de curvas
    de vuelta a vértices significativos (un muro recto vuelve a ser 1 tramo)."""
    n = len(pts)
    if n <= 2 or tol <= 0:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = pts[i]
        bx, by = pts[j]
        dx, dy = bx - ax, by - ay
        seg_len2 = dx * dx + dy * dy
        dmax, imax = -1.0, -1
        for k in range(i + 1, j):
            px, py = pts[k]
            if seg_len2 == 0.0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
                t = max(0.0, min(1.0, t))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > dmax:
                dmax, imax = d, k
        if dmax > tol:
            keep[imax] = True
            stack.append((i, imax))
            stack.append((imax, j))
    return [p for p, k in zip(pts, keep) if k]


def _seg_length(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _path_length(pts: list[tuple[float, float]]) -> float:
    return sum(_seg_length(a, b) for a, b in zip(pts, pts[1:]))


def _polygon_area(ring: list[tuple[float, float]]) -> float:
    n = len(ring)
    acc = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


# ---------------------------------------------------------------------------
# Encuadre (marco compartido entre render y elementos)
# ---------------------------------------------------------------------------

def _visible_layers_default(doc) -> set[str]:
    """Capas visibles como en AutoCAD: ni DEFPOINTS, ni apagadas/congeladas."""
    visible: set[str] = set()
    for layer in doc.layers:
        name = layer.dxf.name
        if name.upper() == "DEFPOINTS":
            continue
        try:
            if layer.is_off() or layer.is_frozen():
                continue
        except Exception:
            pass
        visible.add(name)
    return visible


def _entity_boxes(msp, visible: set[str]) -> list[tuple[tuple[float, float, float, float], object]]:
    """[(bbox_wcs, entity)] de las entidades en capas visibles."""
    lower = {v.lower() for v in visible}
    out: list[tuple[tuple[float, float, float, float], object]] = []
    for e in msp:
        if getattr(e.dxf, "layer", "0").lower() not in lower:
            continue
        b = ezbbox.extents([e], fast=True)
        if b.has_data:
            out.append(((b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y), e))
    return out


def _core_bounds(bboxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    """Bounds del contenido real, descartando outliers (puntos perdidos muy
    lejos del dibujo). 3×IQR sobre centros y solo con muestra suficiente:
    con 1.5×IQR un ala legítima del edificio puede quedar fuera del encuadre.
    """
    if not bboxes:
        return (0.0, 0.0, 1.0, 1.0)
    valid = bboxes
    n = len(bboxes)
    if n >= 8:
        cx = [(b[0] + b[2]) / 2.0 for b in bboxes]
        cy = [(b[1] + b[3]) / 2.0 for b in bboxes]
        cx_sorted = sorted(cx)
        cy_sorted = sorted(cy)
        q1_x, q3_x = cx_sorted[int(n * 0.25)], cx_sorted[int(n * 0.75)]
        q1_y, q3_y = cy_sorted[int(n * 0.25)], cy_sorted[int(n * 0.75)]
        iqr_x = max(q3_x - q1_x, 1e-6)
        iqr_y = max(q3_y - q1_y, 1e-6)
        min_cx, max_cx = q1_x - 3.0 * iqr_x, q3_x + 3.0 * iqr_x
        min_cy, max_cy = q1_y - 3.0 * iqr_y, q3_y + 3.0 * iqr_y
        filtered = [
            b for b, x, y in zip(bboxes, cx, cy)
            if min_cx <= x <= max_cx and min_cy <= y <= max_cy
        ]
        if filtered:
            valid = filtered
    return (
        min(b[0] for b in valid),
        min(b[1] for b in valid),
        max(b[2] for b in valid),
        max(b[3] for b in valid),
    )


def _fit_px_per_m(span_m: float) -> float:
    px_per_m = (_TARGET_MAX_PX - 2 * _MARGIN_PX) / max(span_m, 1e-9)
    px_per_m = max(_MIN_PX_PER_M, min(_MAX_PX_PER_M, px_per_m))
    if span_m * px_per_m + 2 * _MARGIN_PX > _MAX_IMG_PX:
        px_per_m = (_MAX_IMG_PX - 2 * _MARGIN_PX) / span_m
    return px_per_m


def _frame(msp, doc, visible: set[str], override_unit: float | None = None) -> tuple[tuple[float, float, float, float], float, float]:
    """Calcula (bounds_raw, unit, px_per_m) sobre las entidades visibles.

    bounds_raw está en unidades del dibujo; unit convierte a metros.
    El render y to_px() DEBEN usar exactamente este marco.
    """
    boxes = _entity_boxes(msp, visible)
    bounds = _core_bounds([b for b, _ in boxes])

    span_raw = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
    if override_unit is not None:
        unit = override_unit
    else:
        unit = _detect_unit_scale(doc, span_raw)
    px_per_m = _fit_px_per_m(span_raw * unit)

    return bounds, unit, px_per_m


def _make_to_px(bounds: tuple[float, float, float, float], px_per_unit: float):
    gx1, _, _, gy2 = bounds

    def to_px(x: float, y: float) -> tuple[float, float]:
        return (
            (x - gx1) * px_per_unit + _MARGIN_PX,
            (gy2 - y) * px_per_unit + _MARGIN_PX,
        )

    return to_px


# ---------------------------------------------------------------------------
# Render vectorial (PDF de fondo)
# ---------------------------------------------------------------------------

class _LayerTaggedAx:
    """Proxy del Axes que etiqueta cada artista con gid="layer-<capa>".

    matplotlib propaga el gid como atributo `id` del SVG, lo que permite
    prender/apagar capas desde el frontend con CSS. Cubre TODOS los métodos
    con los que MatplotlibBackend agrega artistas: add_line, add_patch,
    add_collection, add_image, scatter y fill.
    """

    def __init__(self, ax):
        self._ax = ax
        self.current_layer = "0"

    def _tag(self, artist):
        try:
            artist.set_gid(f"layer-{self.current_layer}")
        except Exception:
            pass
        return artist

    def add_line(self, line):
        return self._ax.add_line(self._tag(line))

    def add_patch(self, patch):
        return self._ax.add_patch(self._tag(patch))

    def add_collection(self, collection):
        return self._ax.add_collection(self._tag(collection))

    def add_image(self, image):
        return self._ax.add_image(self._tag(image))

    def scatter(self, *args, **kwargs):
        return self._tag(self._ax.scatter(*args, **kwargs))

    def fill(self, *args, **kwargs):
        artists = self._ax.fill(*args, **kwargs)
        for art in artists:
            self._tag(art)
        return artists

    def text(self, *args, **kwargs):
        return self._tag(self._ax.text(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._ax, name)


def _render_svg(
    doc,
    visible_layers: set[str],
    bounds: tuple[float, float, float, float],
    px_per_unit: float,
    out_path: Path,
    fmt: str = "svg",
    entities=None,
) -> None:
    """Plotea el modelspace a SVG monocromo con un grupo por capa.

    El viewBox queda 1:1 con el espacio px de to_px() (figura a 72 dpi).
    Las capas se dibujan en LOTES con Frontend.draw_entities() para fijar el
    gid de cada artista: Frontend NUNCA llama backend.enter_entity(), así que
    un hook ahí no se ejecuta y todo quedaría como "layer-0".
    """
    gx1, gy1, gx2, gy2 = bounds
    margin_u = _MARGIN_PX / px_per_unit
    x_lim = (gx1 - margin_u, gx2 + margin_u)
    y_lim = (gy1 - margin_u, gy2 + margin_u)
    img_w = (gx2 - gx1 + 2 * margin_u) * px_per_unit
    img_h = (gy2 - gy1 + 2 * margin_u) * px_per_unit

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(max(img_w / 72.0, 1.0), max(img_h / 72.0, 1.0)), dpi=72)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor("white")

    proxy = _LayerTaggedAx(ax)
    # adjust_figure=False: el backend redimensionaría la figura y rompería la
    # relación 1:1 viewBox ↔ px que el visor necesita para alinear elementos.
    backend = MatplotlibBackend(proxy, adjust_figure=False)
    ctx = RenderContext(doc)
    ctx.set_current_layout(doc.modelspace())
    config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.BLACK,
    )
    frontend = Frontend(ctx, backend, config=config)

    vis = {name.lower() for name in visible_layers}
    by_layer: defaultdict[str, list] = defaultdict(list)
    # `entities` permite renderizar solo un recorte (las entidades de una
    # región): el SVG resultante es chico y el visor se mantiene fluido.
    for entity in (entities if entities is not None else doc.modelspace()):
        by_layer[getattr(entity.dxf, "layer", "0")].append(entity)
    for layer_name in sorted(by_layer):
        if layer_name.lower() not in vis:
            continue
        proxy.current_layer = layer_name
        frontend.draw_entities(by_layer[layer_name])
    backend.finalize()

    # El backend fija aspect="equal", que pisa los límites exactos. La figura
    # ya tiene la relación de aspecto de los límites: "auto" mantiene escala.
    ax.set_aspect("auto")
    ax.set_xlim(*x_lim)
    ax.set_ylim(*y_lim)
    fig.savefig(out_path, format=fmt, pad_inches=0)
    plt.close(fig)


def _invalidate_raster_cache(plan: "Plan") -> None:
    pdf = Path(plan.pdf_path)
    for png in pdf.parent.glob(f"{pdf.stem}_p*.png"):
        png.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Punto de entrada público: importación
# ---------------------------------------------------------------------------

def build_dxf_plan(
    project_id: int, content: bytes, filename: str, db: Session
) -> tuple[Plan, int]:
    """Parsea DXF/DWG → PDF vectorial de fondo → Plan en BD.
    No crea DetectedElements. El caller hace commit. Devuelve (plan, 0).
    """
    is_dwg = filename.lower().endswith(".dwg")
    suffix  = ".dwg" if is_dwg else ".dxf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        if is_dwg:
            doc = _read_dwg(tmp_path)
        else:
            doc = ezdxf.readfile(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo {suffix[1:].upper()}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    msp = doc.modelspace()
    visible = _visible_layers_default(doc)
    boxes = _entity_boxes(msp, visible)
    bounds = _core_bounds([b for b, _ in boxes])
    span_raw = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
    unit = _detect_unit_scale(doc, span_raw)

    # --- Guardar original ---
    plan_storage = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    plan_storage.mkdir(parents=True, exist_ok=True)
    file_id   = uuid.uuid4().hex
    orig_path = plan_storage / f"{file_id}{suffix}"
    orig_path.write_bytes(content)
    if is_dwg:
        # Guardar también la conversión a DXF: las lecturas posteriores
        # (capas, mapeo, previews) no vuelven a pasar por ODA Converter.
        try:
            doc.saveas(plan_storage / f"{file_id}.dxf")
        except Exception:
            pass

    # La página inicial es el OVERVIEW PNG liviano de toda la lámina, no un
    # SVG vectorial: una lámina real tiene >10k entidades y su SVG pesa
    # decenas de MB (visor lentísimo). Los SVG nítidos se generan recién al
    # aplicar los recortes, que son chicos.
    pdf_path = orig_path.with_name(f"{orig_path.stem}_p1.png")
    ov_scale = _render_overview_png(boxes, bounds, pdf_path)
    px_per_m = ov_scale / unit  # px por metro del overview (aproximado)

    plan = Plan(
        project_id=project_id,
        original_filename=filename,
        pdf_path=str(pdf_path),
        dpi=72,
        page=1,
        page_count=1,
        scale_px_per_m=round(px_per_m, 4),
        scale_source="dxf",
        page_scales={"1": round(px_per_m, 4)},
        status="ready",
    )
    db.add(plan)
    db.flush()

    return plan, 0


# ---------------------------------------------------------------------------
# Carga del archivo CAD original
# ---------------------------------------------------------------------------

def _read_dwg(dwg_path: str):
    """Convierte un DWG a DXF con ODAFileConverter bajo xvfb-run (headless) y
    devuelve el documento ezdxf ya parseado.

    ODAFileConverter es una app Qt; en un servidor sin display falla. `xvfb-run`
    le provee un display X11 efímero por invocación (sin daemon que coordinar).
    Args de ODAFileConverter: <in_dir> <out_dir> <version> <type> <recurse> <audit> <filter>.
    """
    if not shutil.which("ODAFileConverter"):
        raise HTTPException(
            status_code=422,
            detail=(
                "El servidor no tiene ODA File Converter instalado para leer DWG. "
                "Exportá el archivo como DXF desde AutoCAD: "
                "Archivo → Guardar como → DXF AutoCAD 2010 (.dxf)"
            ),
        )

    in_dir = tempfile.mkdtemp(prefix="dwgin_")
    out_dir = tempfile.mkdtemp(prefix="dwgout_")
    try:
        shutil.copy(dwg_path, os.path.join(in_dir, "input.dwg"))
        # XDG_RUNTIME_DIR evita el warning de Qt; no es estrictamente necesario.
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/tmp/runtime-oda")
        os.makedirs(env["XDG_RUNTIME_DIR"], exist_ok=True)

        cmd = [
            "xvfb-run", "-a",
            "ODAFileConverter", in_dir, out_dir,
            "ACAD2010", "DXF", "0", "1", "*.dwg",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
        except FileNotFoundError:
            raise HTTPException(422, "xvfb-run no está instalado en el servidor.")

        out_dxf = os.path.join(out_dir, "input.dxf")
        if not os.path.exists(out_dxf) or os.path.getsize(out_dxf) == 0:
            err = result.stderr.decode("utf-8", errors="ignore")[:400]
            raise HTTPException(
                status_code=400,
                detail=f"No se pudo convertir el DWG (archivo vacío o no soportado). {err}".strip(),
            )
        # readfile carga todo en memoria; tras volver, el doc es independiente del archivo.
        return ezdxf.readfile(out_dxf)
    finally:
        shutil.rmtree(in_dir, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)


def _source_path(plan: "Plan") -> Path:
    """Path del archivo CAD original asociado al plan.

    plan.pdf_path apunta al PDF renderizado ({id}_p1.pdf); el CAD original
    vive al lado como {id}.dxf / {id}.dwg. Se prefiere el .dxf porque para
    los DWG la conversión ya se guardó en el import.
    """
    pdf = Path(plan.pdf_path)
    if pdf.suffix.lower() in (".dxf", ".dwg") and pdf.exists():
        return pdf  # filas viejas donde pdf_path era el CAD directamente
    stem = pdf.stem
    if stem.endswith("_p1"):
        stem = stem[:-3]
    for ext in (".dxf", ".dwg"):
        cand = pdf.with_name(stem + ext)
        if cand.exists():
            return cand
    raise HTTPException(400, "El plano no tiene un archivo DXF/DWG asociado")


def _load_doc(plan: "Plan"):
    file_path = _source_path(plan)
    if file_path.suffix.lower() == ".dwg":
        return _read_dwg(str(file_path))
    return ezdxf.readfile(str(file_path))


# ---------------------------------------------------------------------------
# API pública: obtener capas y aplicar mapeo
# ---------------------------------------------------------------------------

def get_dxf_info(plan: "Plan") -> dict:
    """Devuelve lista de capas y dimensiones físicas en unidades del dibujo."""
    doc = _load_doc(plan)
    msp = doc.modelspace()

    layer_counts: defaultdict[str, int] = defaultdict(int)
    for entity in msp:
        try:
            layer_counts[entity.dxf.layer] += 1
        except AttributeError:
            pass

    layers_list = []
    for layer_name, count in sorted(layer_counts.items(), key=lambda x: -x[1]):
        if layer_name.upper() == "DEFPOINTS":
            continue
        layer_obj = doc.layers.get(layer_name)
        aci = abs(layer_obj.dxf.color) if layer_obj and layer_obj.dxf.hasattr("color") else 7
        rgb = _aci_to_paper_rgb(aci)
        layers_list.append({
            "name": layer_name,
            "color_rgb": list(rgb),
            "entity_count": count,
            "suggested_type": _suggest_type(layer_name),
        })

    visible = _visible_layers_default(doc)
    override_unit = plan.page_scales.get("dxf_unit") if plan.page_scales else None
    bounds, unit, _ = _frame(msp, doc, visible, override_unit)
    w_units = bounds[2] - bounds[0]
    h_units = bounds[3] - bounds[1]
    
    if unit >= 1.0: unit_str = "m"
    elif unit >= 0.01: unit_str = "cm"
    else: unit_str = "mm"

    return {
        "layers": layers_list,
        "width_units": round(w_units, 2),
        "height_units": round(h_units, 2),
        "suggested_unit": unit_str,
        # Marco del overview para mapear recortes del frontend → unidades.
        "overview": {
            "bounds": [round(v, 3) for v in bounds],
            "regions": _load_regions(plan) or [],
            "region_types": _load_region_types(plan) or [],
        },
    }


# ---------------------------------------------------------------------------
# Overview de la lámina + recortes (regiones) persistidos
# ---------------------------------------------------------------------------

# Lado mayor del overview. Una lámina trae varias vistas: a 1600px cada vista
# quedaba en ~300px e ilegible; 4800px permite hacer zoom y reconocer plantas.
_OVERVIEW_MAX_PX = 4800


def _regions_path(plan: "Plan") -> Path:
    src = _source_path(plan)
    return src.with_name(f"{src.stem}_regions.json")


def _load_regions(plan: "Plan") -> Optional[list[list[float]]]:
    try:
        path = _regions_path(plan)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [[float(v) for v in r[:4]] for r in data]
    except Exception:
        pass
    return None


def _load_region_types(plan: "Plan") -> Optional[list[str]]:
    """Tipo de cada recorte ("planta" | "corte"), 5to elemento del JSON.

    Recortes guardados antes de esta feature no traen tipo → "planta".
    """
    try:
        path = _regions_path(plan)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [
                    str(r[4]) if len(r) > 4 and r[4] in ("planta", "corte") else "planta"
                    for r in data
                ]
    except Exception:
        pass
    return None


def _save_regions(
    plan: "Plan", regions: list[list[float]], types: Optional[list[str]] = None
) -> None:
    try:
        data: list[list] = []
        for i, r in enumerate(regions):
            t = types[i] if types and i < len(types) else "planta"
            data.append([*r[:4], t if t in ("planta", "corte") else "planta"])
        _regions_path(plan).write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _render_overview_png(
    boxes: list[tuple[tuple[float, float, float, float], object]],
    bounds: tuple[float, float, float, float],
    out_path: Path,
) -> float:
    """PNG liviano de la lámina completa. Devuelve la escala px/unidad usada.

    El frontend dibuja rectángulos sobre esta imagen para elegir qué vistas
    computar; deja un padding fijo de 10 px que el frontend descuenta.
    """
    gx1, gy1, gx2, gy2 = bounds
    span = max(gx2 - gx1, gy2 - gy1, 1e-9)
    flat_dist = span / 3000.0

    scale = (_OVERVIEW_MAX_PX - 20) / span
    img_w = max(int((gx2 - gx1) * scale) + 20, 64)
    img_h = max(int((gy2 - gy1) * scale) + 20, 64)

    def tp(x: float, y: float) -> tuple[float, float]:
        return ((x - gx1) * scale + 10, (gy2 - y) * scale + 10)

    img = Image.new("RGB", (img_w, img_h), _PREVIEW_BG)
    draw = ImageDraw.Draw(img)
    for _, entity in boxes:
        if entity.dxftype() == "INSERT":
            try:
                for sub in entity.virtual_entities():
                    p = _entity_wcs_points(sub, flat_dist)
                    if p and len(p) >= 2:
                        draw.line([tp(x, y) for x, y in p], fill=(70, 80, 95), width=1)
            except Exception:
                pass
        else:
            p = _entity_wcs_points(entity, flat_dist)
            if p and len(p) >= 2:
                draw.line([tp(x, y) for x, y in p], fill=(70, 80, 95), width=1)

    img.save(out_path)
    return scale


def get_dxf_overview(plan: "Plan") -> Path:
    """PNG de toda la lámina para el selector de recortes del wizard.

    El import ya lo genera como página inicial ({id}_p1.png); si el plan ya
    pasó por apply (pdf_path es .svg), se genera/cachea {id}_overview.png.
    El mapeo px↔unidades del frontend usa overview.bounds de get_dxf_info,
    que sale de los MISMOS helpers (_entity_boxes + _core_bounds).
    """
    def _is_current_res(p: Path) -> bool:
        """True si el PNG cacheado ya tiene la resolución vigente."""
        try:
            with Image.open(p) as im:
                return max(im.width, im.height) >= _OVERVIEW_MAX_PX - 40
        except Exception:
            return False

    pdf = Path(plan.pdf_path)
    if pdf.suffix.lower() == ".png" and pdf.exists() and _is_current_res(pdf):
        return pdf

    src = _source_path(plan)
    out_path = src.with_name(f"{src.stem}_overview.png")
    if out_path.exists() and _is_current_res(out_path):
        return out_path

    doc = _load_doc(plan)
    msp = doc.modelspace()
    boxes = _entity_boxes(msp, _visible_layers_default(doc))
    bounds = _core_bounds([b for b, _ in boxes])
    _render_overview_png(boxes, bounds, out_path)
    return out_path


def _fuse_parallel_faces(
    els: list[DetectedElement], px_per_m: float
) -> list[DetectedElement]:
    """Segunda pasada del merge de muros: fusiona las DOS CARAS de un mismo
    muro (líneas paralelas a 0.04–0.55 m con solape) en una sola línea sobre
    el EJE. Un muro = una línea recta; el ancho/alto se cargan como atributos.
    Itera hasta que no quede ningún par fusionable."""
    changed = True
    while changed:
        changed = False
        used = [False] * len(els)
        out: list[DetectedElement] = []
        for i, a in enumerate(els):
            if used[i]:
                continue
            pa = a.geometry["points"]
            ax, ay, bx, by = pa[0], pa[1], pa[2], pa[3]
            da = math.hypot(bx - ax, by - ay)
            if da == 0:
                used[i] = True
                out.append(a)
                continue
            ux, uy = (bx - ax) / da, (by - ay) / da

            fused = False
            for j in range(i + 1, len(els)):
                if used[j]:
                    continue
                pb = els[j].geometry["points"]
                cx, cy, dx, dy = pb[0], pb[1], pb[2], pb[3]
                db = math.hypot(dx - cx, dy - cy)
                if db == 0:
                    continue
                vx, vy = (dx - cx) / db, (dy - cy) / db
                if abs(ux * vx + uy * vy) < 0.95:
                    continue
                # Separación perpendicular entre líneas (en metros).
                off_c = -uy * (cx - ax) + ux * (cy - ay)
                off_d = -uy * (dx - ax) + ux * (dy - ay)
                sep_m = (abs(off_c) + abs(off_d)) / 2 / px_per_m
                if not (0.04 <= sep_m <= 0.55):
                    continue
                # Solape de intervalos proyectados sobre el eje de `a`.
                t_c = ux * (cx - ax) + uy * (cy - ay)
                t_d = ux * (dx - ax) + uy * (dy - ay)
                lo = max(0.0, min(t_c, t_d))
                hi = min(da, max(t_c, t_d))
                if hi - lo < 0.5 * min(da, db):
                    continue

                # Fusionar: eje a mitad de separación, intervalo = unión.
                mid = (off_c + off_d) / 4  # promedio de offsets / 2 (a está en 0)
                t1 = min(0.0, t_c, t_d)
                t2 = max(da, t_c, t_d)
                nx = -uy, ux
                p1 = (ax + t1 * ux + mid * nx[0], ay + t1 * uy + mid * nx[1])
                p2 = (ax + t2 * ux + mid * nx[0], ay + t2 * uy + mid * nx[1])
                out.append(DetectedElement(
                    plan_id=a.plan_id,
                    page=a.page,
                    type=a.type,
                    geometry={**a.geometry, "points": [
                        round(p1[0], 2), round(p1[1], 2),
                        round(p2[0], 2), round(p2[1], 2),
                    ]},
                    length_m=round((t2 - t1) / px_per_m, 3),
                    height_m=a.height_m,
                    source=a.source,
                ))
                used[i] = used[j] = True
                fused = True
                changed = True
                break
            if not fused and not used[i]:
                used[i] = True
                out.append(a)
        els = out
    return els


def _cluster_escaleras(
    els: list[DetectedElement], px_per_m: float
) -> list[DetectedElement]:
    """Una escalera en CAD son decenas de trazos (escalones, flecha, pedadas).
    Agrupa los elementos 'escalera' cercanos (≤0.4 m) y emite UN polígono bbox
    por grupo, con su área — que es lo que computa el presupuesto."""
    if not els:
        return []
    boxes = []
    for e in els:
        pts = e.geometry.get("points") or []
        xs = pts[0::2]
        ys = pts[1::2]
        if not xs:
            continue
        boxes.append([min(xs), min(ys), max(xs), max(ys), e])
    tol = 0.4 * px_per_m
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if (a[0] - tol <= b[2] and b[0] - tol <= a[2]
                    and a[1] - tol <= b[3] and b[1] - tol <= a[3]):
                parent[find(i)] = find(j)

    groups: dict[int, list] = defaultdict(list)
    for i in range(len(boxes)):
        groups[find(i)].append(boxes[i])

    out: list[DetectedElement] = []
    for members in groups.values():
        x1 = min(m[0] for m in members)
        y1 = min(m[1] for m in members)
        x2 = max(m[2] for m in members)
        y2 = max(m[3] for m in members)
        w_m = (x2 - x1) / px_per_m
        h_m = (y2 - y1) / px_per_m
        area = w_m * h_m
        # Una escalera real ocupa 1–25 m²; lo demás es ruido o un símbolo suelto.
        if area < 1.0 or area > 25.0 or max(w_m, h_m) > 8.0:
            continue
        ref = members[0][4]
        out.append(DetectedElement(
            plan_id=ref.plan_id,
            page=ref.page,
            type="escalera",
            geometry={"points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y1, 2),
                                 round(x2, 2), round(y2, 2), round(x1, 2), round(y2, 2)]},
            area_m2=round(area, 2),
            height_m=2.8,
            source=ref.source,
        ))
    return out


def _bridge_walls_over_openings(
    walls: list[DetectedElement],
    openings: list[DetectedElement],
    px_per_m: float,
) -> list[DetectedElement]:
    """Une muros colineales cortados por un vano cuando hay una ABERTURA en el
    hueco: el muro queda continuo (pasa por encima de la abertura) y el cómputo
    le resta después las medidas de la abertura (dintel/antepecho incluidos).

    El CAD dibuja las caras del muro interrumpidas en cada puerta/ventana; sin
    este puente el área del muro ignoraría la pared sobre el dintel."""
    if not walls or not openings:
        return walls

    centers = []
    for o in openings:
        p = o.geometry["points"]
        centers.append(((p[0] + p[2]) / 2, (p[1] + p[3]) / 2))

    max_gap_px = 3.0 * px_per_m       # vano más grande que puenteamos
    axis_tol_px = 0.45 * px_per_m     # distancia abertura ↔ eje del muro
    margin_px = 0.30 * px_per_m       # tolerancia del centro dentro del gap

    changed = True
    while changed:
        changed = False
        out: list[DetectedElement] = []
        used = [False] * len(walls)
        for i, a in enumerate(walls):
            if used[i]:
                continue
            pa = a.geometry["points"]
            ax, ay, bx, by = pa[0], pa[1], pa[2], pa[3]
            da = math.hypot(bx - ax, by - ay)
            if da == 0:
                used[i] = True
                out.append(a)
                continue
            ux, uy = (bx - ax) / da, (by - ay) / da

            bridged = False
            for j in range(i + 1, len(walls)):
                if used[j]:
                    continue
                pb = walls[j].geometry["points"]
                cx, cy, dx, dy = pb[0], pb[1], pb[2], pb[3]
                db = math.hypot(dx - cx, dy - cy)
                if db == 0:
                    continue
                vx, vy = (dx - cx) / db, (dy - cy) / db
                if abs(ux * vx + uy * vy) < 0.97:
                    continue
                # Colineal: offset perpendicular chico entre ambos ejes.
                off = abs(-uy * (cx - ax) + ux * (cy - ay))
                if off > 0.15 * px_per_m:
                    continue
                # Gap entre intervalos sobre el eje de `a`.
                t_c = ux * (cx - ax) + uy * (cy - ay)
                t_d = ux * (dx - ax) + uy * (dy - ay)
                lo_b, hi_b = min(t_c, t_d), max(t_c, t_d)
                if lo_b > da:           # b está después de a
                    gap_lo, gap_hi = da, lo_b
                elif hi_b < 0:          # b está antes de a
                    gap_lo, gap_hi = hi_b, 0.0
                else:
                    continue            # se solapan: eso lo resuelve el merge
                gap = gap_hi - gap_lo
                if gap <= 0 or gap > max_gap_px:
                    continue
                # ¿Hay una abertura dentro del gap, sobre este eje?
                has_opening = False
                for ocx, ocy in centers:
                    t_o = ux * (ocx - ax) + uy * (ocy - ay)
                    d_o = abs(-uy * (ocx - ax) + ux * (ocy - ay))
                    if d_o <= axis_tol_px and gap_lo - margin_px <= t_o <= gap_hi + margin_px:
                        has_opening = True
                        break
                if not has_opening:
                    continue

                t1 = min(0.0, lo_b)
                t2 = max(da, hi_b)
                out.append(DetectedElement(
                    plan_id=a.plan_id,
                    page=a.page,
                    type=a.type,
                    geometry={**a.geometry, "points": [
                        round(ax + t1 * ux, 2), round(ay + t1 * uy, 2),
                        round(ax + t2 * ux, 2), round(ay + t2 * uy, 2),
                    ]},
                    length_m=round((t2 - t1) / px_per_m, 3),
                    height_m=a.height_m,
                    source=a.source,
                ))
                used[i] = used[j] = True
                bridged = True
                changed = True
                break
            if not bridged and not used[i]:
                used[i] = True
                out.append(a)
        walls = out
    return walls


def _merge_segments(
    elements: list[DetectedElement], px_per_m: float
) -> list[DetectedElement]:
    """Colapsa segmentos casi colineales y cercanos (muros a doble línea,
    tramos partidos) en elementos únicos, y descarta tramos < 0.2 m."""
    result: list[DetectedElement] = []
    el_by_type: defaultdict[str, list[DetectedElement]] = defaultdict(list)
    for el in elements:
        el_by_type[el.type].append(el)

    for el_type, els in el_by_type.items():
        if el_type not in _SEGMENT_TYPES:
            result.extend(els)
            continue

        groups: list[tuple[float, float, float, float, list]] = []
        dist_tol_px = 0.4 * px_per_m

        for el in els:
            if (el.length_m or 0) < 0.2:
                continue
            pts = el.geometry["points"]
            sx1, sy1, sx2, sy2 = pts[0], pts[1], pts[2], pts[3]
            dx, dy = sx2 - sx1, sy2 - sy1
            dlen = math.hypot(dx, dy)
            if dlen == 0:
                continue
            ux, uy = dx / dlen, dy / dlen

            placed = False
            for g_ux, g_uy, bx, by, seg_list in groups:
                if abs(ux * g_ux + uy * g_uy) > 0.95:
                    dist = abs(-g_uy * (sx1 - bx) + g_ux * (sy1 - by))
                    if dist < dist_tol_px:
                        seg_list.append((sx1, sy1, sx2, sy2, el))
                        placed = True
                        break
            if not placed:
                groups.append((ux, uy, sx1, sy1, [(sx1, sy1, sx2, sy2, el)]))

        for ux, uy, bx, by, seg_list in groups:
            intervals = []
            for sx1, sy1, sx2, sy2, el in seg_list:
                t1 = ux * (sx1 - bx) + uy * (sy1 - by)
                t2 = ux * (sx2 - bx) + uy * (sy2 - by)
                intervals.append((min(t1, t2), max(t1, t2), el))
            intervals.sort(key=lambda x: x[0])
            merged = [intervals[0]]
            for start, end, el in intervals[1:]:
                last_start, last_end, _ = merged[-1]
                if start <= last_end + 0.3 * px_per_m:  # gap ≤ 0.3 m
                    merged[-1] = (last_start, max(last_end, end), merged[-1][2])
                else:
                    merged.append((start, end, el))
            for start, end, el in merged:
                mlen_m = (end - start) / px_per_m
                if mlen_m < 0.2:
                    continue
                # Instancia nueva: deepcopy de un objeto ORM arrastra el
                # estado interno de SQLAlchemy y corrompe la sesión.
                result.append(DetectedElement(
                    plan_id=el.plan_id,
                    page=el.page,
                    type=el.type,
                    geometry={
                        **el.geometry,
                        "points": [round(bx + start * ux, 2), round(by + start * uy, 2),
                                   round(bx + end * ux, 2), round(by + end * uy, 2)],
                    },
                    area_m2=el.area_m2,
                    length_m=round(mlen_m, 3),
                    source=el.source,
                ))

    # Segunda pasada solo para muros: colapsar las dos caras en el eje.
    walls = [e for e in result if e.type == "wall"]
    others = [e for e in result if e.type != "wall"]
    return others + _fuse_parallel_faces(walls, px_per_m)


def apply_layer_mapping(
    plan: "Plan",
    mapping: dict[str, Optional[str]],
    db: Session,
    regions: Optional[list[list[float]]] = None,
    region_types: Optional[list[str]] = None,
) -> int:
    """Crea DetectedElements a partir del mapeo capa→tipo y de los RECORTES.

    Una lámina CAD real contiene varias vistas (plantas, cortes, planillas) en
    un solo modelspace; `regions` son rectángulos [x1,y1,x2,y2] en unidades de
    dibujo elegidos por el usuario: cada recorte se vuelve una PÁGINA del plan
    con su propio encuadre, escala y SVG. Solo las entidades cuyo centro cae
    dentro del recorte generan elementos (las aberturas de un corte o una
    planilla quedan afuera).

    Si no llegan regiones se usan las persistidas en {id}_regions.json (re-apply
    desde el visor) o, como último recurso, todo el contenido como una página.
    Re-aplicar reemplaza los elementos source="dxf" anteriores.
    """
    doc = _load_doc(plan)
    msp = doc.modelspace()

    hidden = {name for name, t in mapping.items() if not t}
    typed = {name for name, t in mapping.items() if t and t != CONTEXT_TYPE}
    # Las capas ausentes del mapeo quedan visibles (el modal del visor solo
    # manda las capas tipadas y no debe borrar el contexto).
    visible = (_visible_layers_default(doc) | typed) - hidden

    # typed ⊆ visible (un mapeo no puede ser tipo y oculto a la vez).
    boxes = _entity_boxes(msp, visible)
    vis_lower = {v.lower() for v in visible}
    if regions:
        regions = [
            [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]
            for r in regions
        ]
        _save_regions(plan, regions, region_types)
    else:
        regions = _load_regions(plan) or [list(_core_bounds([b for b, _ in boxes]))]
        if region_types is None:
            region_types = _load_region_types(plan)
    # Tipo de cada vista: las marcadas "corte" (cortes/fachadas/elevaciones)
    # se renderizan como página pero NO generan elementos — son solo
    # referencia visual de alturas; computarlas duplicaría muros.
    types = [
        (region_types[i] if region_types and i < len(region_types) else "planta")
        for i in range(len(regions))
    ]

    override_unit = plan.page_scales.get("dxf_unit") if plan.page_scales else None
    span0 = max(regions[0][2] - regions[0][0], regions[0][3] - regions[0][1], 1e-9)
    unit = override_unit if override_unit else _detect_unit_scale(doc, span0)
    flat_dist = _FLATTEN_M / unit
    simp_tol = _SIMPLIFY_M / unit

    # Re-aplicar el mapeo reemplaza lo generado antes desde el CAD.
    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan.id,
        DetectedElement.source == "dxf",
    ).delete(synchronize_session=False)

    svg_base = Path(plan.pdf_path)
    if svg_base.suffix.lower() != ".svg":
        svg_base = svg_base.with_suffix(".svg")
        plan.pdf_path = str(svg_base)
    stem = svg_base.stem
    if stem.endswith("_p1"):
        stem = stem[:-3]

    def _intersects(b: tuple[float, float, float, float], r: list[float]) -> bool:
        return not (b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3])

    def _center_in(b: tuple[float, float, float, float], r: list[float]) -> bool:
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]

    total = 0
    new_scales: dict = {}
    for page, region in enumerate(regions, start=1):
        is_corte = types[page - 1] == "corte"
        bounds = (region[0], region[1], region[2], region[3])
        # Resolución anclada en PÍXELES (no en metros): el lado mayor de cada
        # página siempre sale ~_TARGET_MAX_PX. Una unidad mal elegida ya no
        # puede degradar el render a una miniatura ilegible — solo afecta las
        # medidas en metros, que se corrigen re-eligiendo la unidad.
        span_u = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
        px_per_unit = (_TARGET_MAX_PX - 2 * _MARGIN_PX) / span_u
        px_per_m = px_per_unit / unit
        to_px = _make_to_px(bounds, px_per_unit)

        page_elements: list[DetectedElement] = []
        render_entities = []
        for b, entity in boxes:
            layer_name = getattr(entity.dxf, "layer", "0")
            if layer_name.lower() in vis_lower and _intersects(b, region):
                render_entities.append(entity)
            if is_corte:
                continue  # la vista de corte se ve pero no genera elementos
            el_type = mapping.get(layer_name)
            if not el_type or el_type == CONTEXT_TYPE or not _center_in(b, region):
                continue
            if entity.dxftype() == "INSERT":
                page_elements.extend(_insert_to_detected(
                    entity, el_type, plan.id, to_px, px_per_unit, unit, flat_dist,
                    page=page,
                ))
            else:
                page_elements.extend(_entity_to_detected(
                    entity, el_type, plan.id, to_px, px_per_unit, unit, flat_dist,
                    simp_tol, page=page,
                ))

        page_elements = _merge_segments(page_elements, px_per_m)
        # Muro continuo sobre cada vano con abertura: el cómputo le resta
        # después las medidas de la abertura (dintel/antepecho incluidos).
        walls = [e for e in page_elements if e.type == "wall"]
        openings = [e for e in page_elements if e.type == "opening"]
        escaleras = [e for e in page_elements if e.type == "escalera"]
        others = [e for e in page_elements if e.type not in ("wall", "escalera")]
        page_elements = (others
                         + _bridge_walls_over_openings(walls, openings, px_per_m)
                         + _cluster_escaleras(escaleras, px_per_m))

        # Nada debe flotar fuera del lienzo del recorte.
        margin_u = _MARGIN_PX / px_per_unit
        img_w = (bounds[2] - bounds[0] + 2 * margin_u) * px_per_unit
        img_h = (bounds[3] - bounds[1] + 2 * margin_u) * px_per_unit

        def _in_canvas(el: DetectedElement) -> bool:
            pts = el.geometry["points"]
            xs = pts[0::2]
            ys = pts[1::2]
            return not (max(xs) < 0 or min(xs) > img_w or max(ys) < 0 or min(ys) > img_h)

        page_elements = [el for el in page_elements if _in_canvas(el)]
        if page_elements:
            db.add_all(page_elements)
        total += len(page_elements)

        page_svg = svg_base.with_name(f"{stem}_p{page}.svg")
        _render_svg(doc, visible, bounds, px_per_unit, page_svg, entities=render_entities)
        # PNG gemelo (mismos bounds y escala): es la imagen que consumen los
        # detectores de IA, igual que el raster de una página PDF.
        page_png = svg_base.with_name(f"{stem}_p{page}.png")
        _render_svg(doc, visible, bounds, px_per_unit, page_png, fmt="png", entities=render_entities)
        new_scales[str(page)] = round(px_per_m, 4)

    # Borrar SVGs/PNGs de recortes que ya no existen y PNGs cacheados viejos.
    for old in list(svg_base.parent.glob(f"{stem}_p*.svg")) + list(svg_base.parent.glob(f"{stem}_p*.png")):
        try:
            n = int(old.stem[len(stem) + 2:])
            if n > len(regions):
                old.unlink(missing_ok=True)
        except ValueError:
            pass
    _invalidate_raster_cache(plan)

    # El viewBox de cada SVG está 1:1 con el espacio px de su página, así que
    # px_per_m va SIN factor. Se preserva el override de unidad del usuario.
    if plan.page_scales and "dxf_unit" in plan.page_scales:
        new_scales["dxf_unit"] = plan.page_scales["dxf_unit"]
    plan.scale_px_per_m = new_scales.get("1")
    plan.page_scales = new_scales
    plan.page_count = len(regions)
    plan.pdf_path = str(svg_base.with_name(f"{stem}_p1.svg"))

    # page_roles refleja el tipo de cada vista: los cortes quedan marcados
    # para que ningún detector (IA o derivación de recintos) los procese.
    plan.page_roles = {
        str(i + 1): ["cortes"] for i, t in enumerate(types) if t == "corte"
    } or None

    # Derivar recintos geométricamente desde los muros importados (solo
    # vistas planta). Necesita los elementos flusheados y los PNG renderizados,
    # ambos listos a esta altura.
    try:
        from app.services.room_derivation import derive_rooms_for_plan

        db.flush()
        planta_pages = [i + 1 for i, t in enumerate(types) if t != "corte"]
        if planta_pages:
            rooms_created = derive_rooms_for_plan(plan.id, db, only_pages=planta_pages)
            if rooms_created:
                logger.info(
                    "apply_layer_mapping: %d recintos derivados de muros plan=%s",
                    rooms_created, plan.id,
                )
    except Exception:  # noqa: BLE001
        logger.exception("derivación de recintos falló plan=%s (apply sigue)", plan.id)

    return total


# ---------------------------------------------------------------------------
# Conversión entidad → DetectedElement
# ---------------------------------------------------------------------------

def _make_element(
    plan_id: int,
    el_type: str,
    points_px: list[float],
    *,
    page: int = 1,
    length_m: Optional[float] = None,
    area_m2: Optional[float] = None,
    layer: str = "",
) -> DetectedElement:
    # float() porque algunos puntos llegan como np.float64 (ezdxf usa numpy
    # en paths/flattening) y eso no es serializable a JSON.
    geometry: dict = {"points": [round(float(v), 2) for v in points_px]}
    if el_type == "opening":
        up = layer.upper()
        geometry["subtype"] = (
            "window" if any(k in up for k in ("VENTANA", "WINDOW")) else "door"
        )
    return DetectedElement(
        plan_id=plan_id,
        page=page,
        type=el_type,
        geometry=geometry,
        area_m2=None if area_m2 is None else round(float(area_m2), 3),
        length_m=None if length_m is None else round(float(length_m), 3),
        source="dxf",
    )


def _entity_to_detected(
    entity,
    el_type: str,
    plan_id: int,
    to_px,
    px_per_unit: float,
    unit: float,
    flat_dist: float,
    simp_tol: float,
    page: int = 1,
) -> list[DetectedElement]:
    """Convierte una entidad DXF en elementos con la geometría real (WCS)."""
    raw = _entity_wcs_points(entity, flat_dist)
    if not raw or len(raw) < 2:
        return []
    pts = _simplify(raw, simp_tol)
    layer = getattr(entity.dxf, "layer", "")

    if el_type in _SEGMENT_TYPES:
        # Muros/vigas/aberturas son segmentos [x1,y1,x2,y2] en el visor:
        # cada tramo de la polilínea simplificada es un elemento. Un tramo
        # curvo (escalera, muro curvo) queda como varios segmentos cortos
        # cuya longitud total respeta la curva.
        out: list[DetectedElement] = []
        for a, b in zip(pts, pts[1:]):
            length_raw = _seg_length(a, b)
            if length_raw * px_per_unit < _MIN_ELEMENT_PX:
                continue
            pa, pb = to_px(*a), to_px(*b)
            out.append(_make_element(
                plan_id, el_type, [pa[0], pa[1], pb[0], pb[1]],
                length_m=length_raw * unit, layer=layer, page=page,
            ))
        return out

    if el_type in _POLYGON_TYPES:
        ring = pts
        if len(ring) > 2 and _seg_length(ring[0], ring[-1]) < simp_tol:
            ring = ring[:-1]  # sin punto repetido de cierre
        if len(ring) < 3:
            return []  # una línea suelta no define un recinto/columna
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        if (max(xs) - min(xs)) * px_per_unit < _MIN_ELEMENT_PX and \
           (max(ys) - min(ys)) * px_per_unit < _MIN_ELEMENT_PX:
            return []
        flat: list[float] = []
        for x, y in ring:
            px = to_px(x, y)
            flat.extend(px)
        area_raw = _polygon_area(ring)
        perim_raw = _path_length(ring + [ring[0]])
        return [_make_element(
            plan_id, el_type, flat,
            length_m=perim_raw * unit if el_type in ("room", "roof") else None,
            area_m2=area_raw * unit * unit,
            layer=layer, page=page,
        )]

    # Trazados (cloaca / electricidad): polilínea completa.
    length_raw = _path_length(pts)
    if length_raw * px_per_unit < _MIN_ELEMENT_PX:
        return []
    flat = []
    for x, y in pts:
        px = to_px(x, y)
        flat.extend(px)
    return [_make_element(
        plan_id, el_type, flat, length_m=length_raw * unit, layer=layer,
    )]


def _insert_to_detected(
    insert,
    el_type: str,
    plan_id: int,
    to_px,
    px_per_unit: float,
    unit: float,
    flat_dist: float,
    page: int = 1,
) -> list[DetectedElement]:
    """Un bloque (puerta, ventana, cámara…) se convierte en UN solo elemento
    a partir de su bounding box WCS, no uno por cada línea interna."""
    pts: list[tuple[float, float]] = []
    try:
        for sub in insert.virtual_entities():
            p = _entity_wcs_points(sub, flat_dist)
            if p:
                pts.extend(p)
    except Exception:
        return []
    if not pts:
        return []

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    w, h = x2 - x1, y2 - y1
    if w * px_per_unit < _MIN_ELEMENT_PX and h * px_per_unit < _MIN_ELEMENT_PX:
        return []
    layer = getattr(insert.dxf, "layer", "")

    if el_type in _SEGMENT_TYPES:
        # Eje central a lo largo del lado mayor del bloque (ancho de la
        # puerta/ventana), que es lo que el visor dibuja como segmento.
        if w >= h:
            a, b = (x1, (y1 + y2) / 2), (x2, (y1 + y2) / 2)
            length_raw = w
        else:
            a, b = ((x1 + x2) / 2, y1), ((x1 + x2) / 2, y2)
            length_raw = h
        pa, pb = to_px(*a), to_px(*b)
        return [_make_element(
            plan_id, el_type, [pa[0], pa[1], pb[0], pb[1]],
            length_m=length_raw * unit, layer=layer, page=page,
        )]

    corners = [(x1, y2), (x2, y2), (x2, y1), (x1, y1)]
    flat: list[float] = []
    for x, y in corners:
        px = to_px(x, y)
        flat.extend(px)
    perim_m = 2 * (w + h) * unit
    if el_type in _POLYGON_TYPES:
        return [_make_element(
            plan_id, el_type, flat,
            length_m=perim_m if el_type in ("room", "roof") else None,
            area_m2=w * h * unit * unit,
            layer=layer, page=page,
        )]
    return [_make_element(plan_id, el_type, flat, length_m=perim_m, layer=layer, page=page)]


# ---------------------------------------------------------------------------
# Previews por capa (PNG con la capa resaltada)
# ---------------------------------------------------------------------------

_PREVIEW_MAX_PX = 720
_PREVIEW_PAD_PX = 10
_PREVIEW_BG  = (255, 255, 255)
_PREVIEW_DIM = (203, 213, 225)  # resto del plano, gris claro
_PREVIEW_HI  = (220, 38, 38)    # capa resaltada, rojo


def _preview_path(plan: "Plan", layer_name: str) -> Path:
    src = _source_path(plan)
    digest = hashlib.md5(layer_name.encode("utf-8")).hexdigest()[:12]
    return src.with_name(f"{src.stem}_layerprev_{digest}.png")


def get_layer_preview(plan: "Plan", layer_name: str) -> Path:
    """PNG con `layer_name` en rojo sobre el resto del plano en gris claro.

    Los previews de TODAS las capas se generan en un solo pase (un solo parse
    del CAD) y se cachean en disco junto al archivo original.
    """
    target = _preview_path(plan, layer_name)
    if target.exists():
        return target

    doc = _load_doc(plan)
    msp = doc.modelspace()

    # Encuadre solo con capas visibles (como AutoCAD): una entidad basura en
    # una capa congelada no debe achicar el dibujo a una tira.
    visible_lower = {v.lower() for v in _visible_layers_default(doc)}
    vis_entities = [
        e for e in msp
        if getattr(e.dxf, "layer", "0").lower() in visible_lower
    ]
    # Tolerancia de aplanado gruesa: es solo una miniatura.
    box = ezbbox.extents(vis_entities, fast=True)
    if box.has_data:
        gx1, gy1 = box.extmin.x, box.extmin.y
        gx2, gy2 = box.extmax.x, box.extmax.y
    else:
        gx1, gy1, gx2, gy2 = 0.0, 0.0, 1.0, 1.0
    span = max(gx2 - gx1, gy2 - gy1, 1e-9)
    flat_dist = span / 500.0

    by_layer: defaultdict[str, list[list[tuple[float, float]]]] = defaultdict(list)
    for entity in msp:
        layer = getattr(entity.dxf, "layer", "0")
        if entity.dxftype() == "INSERT":
            try:
                for sub in entity.virtual_entities():
                    p = _entity_wcs_points(sub, flat_dist)
                    if p and len(p) >= 2:
                        by_layer[layer].append(p)
            except Exception:
                pass
        else:
            p = _entity_wcs_points(entity, flat_dist)
            if p and len(p) >= 2:
                by_layer[layer].append(p)

    if layer_name not in by_layer:
        raise HTTPException(404, f"La capa '{layer_name}' no existe en el archivo")

    scale = (_PREVIEW_MAX_PX - 2 * _PREVIEW_PAD_PX) / span
    img_w = max(int((gx2 - gx1) * scale) + 2 * _PREVIEW_PAD_PX, 32)
    img_h = max(int((gy2 - gy1) * scale) + 2 * _PREVIEW_PAD_PX, 32)

    def tp(x: float, y: float) -> tuple[float, float]:
        return ((x - gx1) * scale + _PREVIEW_PAD_PX, (gy2 - y) * scale + _PREVIEW_PAD_PX)

    base = Image.new("RGB", (img_w, img_h), _PREVIEW_BG)
    draw = ImageDraw.Draw(base)
    for lname, polys in by_layer.items():
        if lname.lower() not in visible_lower:
            continue
        for p in polys:
            draw.line([tp(x, y) for x, y in p], fill=_PREVIEW_DIM, width=1)

    for lname, polys in by_layer.items():
        out_path = _preview_path(plan, lname)
        if out_path.exists():
            continue
        img = base.copy()
        d = ImageDraw.Draw(img)
        for p in polys:
            d.line([tp(x, y) for x, y in p], fill=_PREVIEW_HI, width=2)
        img.save(out_path)

    return target
