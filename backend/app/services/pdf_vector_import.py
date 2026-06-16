"""Import automático de elementos desde PDFs vectoriales con capas CAD.

Muchos PDFs de planos vienen exportados directo de AutoCAD/similar y conservan
las capas (OCG) y la geometría vectorial. De ahí se puede extraer ground truth
exacto — muros, aberturas, cloacas, electricidad — sin IA y sin dibujar a mano:

  1. Al subir un PDF, `try_vector_import(plan_id)` corre en background.
  2. Si el PDF tiene capas reconocibles (nombres con MURO/WALL, ABERTURA, etc.)
     se extrae la geometría por capa, se corrige la rotación de página y se
     convierte a píxeles del raster (dpi del plan).
  3. La escala se calcula desde las cotas del propio PDF (texto "3.50" junto a
     su línea de cota) y se valida por consistencia.
  4. Los muros a doble línea se fusionan en ejes con `_merge_segments` (el
     mismo merge del import DXF). Las aberturas se agrupan por símbolo.
  5. Los elementos se persisten con source="dxf" (geometría de origen CAD),
     que el pipeline de entrenamiento trata como ground truth.

Si el PDF no tiene capas (escaneado o aplanado) la función no hace nada y el
flujo normal (IA + dibujo manual) sigue intacto.
"""

import logging
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Palabras clave (en mayúsculas) para clasificar capas por nombre. Sinónimos
# amplios ES/EN: distintos estudios nombran distinto la misma cosa (muro/pared/
# tabique/mampostería). El substring matchea variantes (CARPINTER → carpintería/
# carpinterias). Lo que ninguna keyword reconozca queda sin clasificar (y, a
# futuro, lo resuelve el fallback LLM semántico).
_WALL_KEYS = ("MURO", "PARED", "WALL", "TABIQUE", "MAMPOSTER")
_OPENING_KEYS = (
    "ABERTURA", "CARPINTER", "PUERTA", "VENTANA", "DOOR", "WINDOW", "VANO",
)
# Cloaca = desagüe SANITARIO (cloacal/primario/secundario, aguas servidas).
# Pluvial se excluye aparte (_PLUVIAL_KEYS) porque es otro sistema.
_CLOACA_KEYS = (
    "CLOACA", "CLOACAL", "SANITARI", "DESAGUE", "DESAGÜE",
    "AGUAS NEGRAS", "AGUAS SERVIDAS", "AGUAS RESIDUALES", "SEWER",
)
_ELEC_KEYS = (
    "ELECTRIC", "ELÉCTRIC", "ILUMINAC", "TABLERO", "TOMACORRIENTE",
    "BOCAS", "TOMAS", "UNIFILAR", "IE-", "IE_",
)
_STAIR_KEYS = ("ESCALERA", "STAIR", "ESCALON", "ESCALÓN")
_SCALE_KEYS = ("COTA",)

# Capas que NUNCA son elementos aunque matcheen (hatches del plotter, etc.)
_EXCLUDE_KEYS = ("PDF32_", "SOLID FILL")

# Pluvial (desagüe de lluvia / pendientes de techo) NO es cloaca: es otro
# sistema y en un plano de techos son flechas de pendiente, no cañerías.
# Como el modelo no tiene clase pluvial, se descarta para no contaminar cloaca
# (matchea ANTES que _CLOACA_KEYS porque "desaguepluvial" contiene DESAGUE).
_PLUVIAL_KEYS = ("PLUVIAL",)

_MIN_WALL_SEG_M = 0.15
_MIN_LINE_M = 0.08
_OPENING_MIN_M = 0.35
_OPENING_MAX_M = 4.0
_OPENING_CLUSTER_GAP_M = 0.12


# Disciplina de la lámina, leída del rótulo ("Plano: ..."). Una lámina CAD
# trae la arquitectura como fondo (xref) en TODAS las disciplinas; sin esto
# los muros/aberturas se duplicaban en cada página (cloacas, vigas, techos,
# electricidad). Cada página aporta SOLO los tipos de su disciplina; los
# recintos se derivan de los muros y caen solos donde están los muros.
_ARCH_LEGEND = ("ARQUITECT", "ALBAÑIL", "ALBANIL", "MAMPOSTER", "DISTRIBUCION", "DISTRIBUCIÓN")
_CLOACA_LEGEND = ("CLOACA", "CLOACAL", "SANITARI", "AGUAS NEGRAS", "AGUAS SERVIDAS")
_ELEC_LEGEND = ("ELECTRIC", "ELÉCTRIC", "ILUMINAC", "UNIFILAR", "TABLERO")


def _page_allowed_types(page) -> set:
    """Tipos de elemento permitidos en la página según su rótulo.

    Estructura, techos, pluvial, agua, gas, solados y planillas no tienen
    extracción propia y su arquitectura es solo fondo → devuelven set vacío
    (la página no aporta nada). Una lámina puede combinar disciplinas
    (ej: "PLANTA GENERAL E INSTALACION ELECTRICA Y SANITARIA").
    """
    up = (page.get_text() or "").upper()
    allowed: set = set()
    if any(k in up for k in _ARCH_LEGEND):
        allowed |= {"wall", "opening", "escalera"}
    if any(k in up for k in _CLOACA_LEGEND):
        allowed.add("cloaca")
    if any(k in up for k in _ELEC_LEGEND):
        allowed.add("electricidad")
    return allowed


def _classify_layer(name: str) -> Optional[str]:
    up = name.upper()
    if any(k in up for k in _EXCLUDE_KEYS):
        return None
    if any(k in up for k in _PLUVIAL_KEYS):
        return None
    if any(k in up for k in _WALL_KEYS):
        return "wall"
    if any(k in up for k in _OPENING_KEYS):
        return "opening"
    if any(k in up for k in _CLOACA_KEYS):
        return "cloaca"
    if any(k in up for k in _ELEC_KEYS):
        return "electricidad"
    if any(k in up for k in _STAIR_KEYS):
        return "escalera"
    return None


def _bezier_pts(p0, p1, p2, p3, n: int = 6) -> list[tuple[float, float]]:
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0.x + 3 * mt * mt * t * p1.x + 3 * mt * t * t * p2.x + t**3 * p3.x
        y = mt**3 * p0.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t**3 * p3.y
        out.append((x, y))
    return out


def _path_polylines(d: dict) -> list[list[tuple[float, float]]]:
    """Polilíneas (en pt, espacio sin rotar) de un path de get_drawings()."""
    polys: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for item in d["items"]:
        kind = item[0]
        if kind == "l":
            p1, p2 = item[1], item[2]
            if cur and abs(cur[-1][0] - p1.x) < 0.01 and abs(cur[-1][1] - p1.y) < 0.01:
                cur.append((p2.x, p2.y))
            else:
                if len(cur) >= 2:
                    polys.append(cur)
                cur = [(p1.x, p1.y), (p2.x, p2.y)]
        elif kind == "c":
            pts = _bezier_pts(item[1], item[2], item[3], item[4])
            if cur and abs(cur[-1][0] - pts[0][0]) < 0.01 and abs(cur[-1][1] - pts[0][1]) < 0.01:
                cur.extend(pts[1:])
            else:
                if len(cur) >= 2:
                    polys.append(cur)
                cur = pts
        elif kind == "re":
            if len(cur) >= 2:
                polys.append(cur)
            cur = []
            r = item[1]
            polys.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
        elif kind == "qu":
            if len(cur) >= 2:
                polys.append(cur)
            cur = []
            q = item[1]
            polys.append([
                (q.ul.x, q.ul.y), (q.ur.x, q.ur.y),
                (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y),
            ])
    if len(cur) >= 2:
        polys.append(cur)
    return polys


def page_scale_pt_per_m(page) -> Optional[float]:
    """pt/m de la página a partir de sus cotas: texto "3.50" junto a una línea
    de cota de la capa de cotas. Mediana sobre todos los matches."""
    import fitz

    words = page.get_text("words")
    dims = []
    for w in words:
        txt = w[4].replace(",", ".")
        if re.fullmatch(r"\d{1,2}\.\d{2}", txt):
            v = float(txt)
            if 0.3 <= v <= 30:
                dims.append((v, fitz.Rect(w[:4])))

    segs = []
    for d in page.get_drawings():
        layer = (d.get("layer") or "").upper()
        if not any(k in layer for k in _SCALE_KEYS):
            continue
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                if max(dx, dy) > 5 and min(dx, dy) < 0.5:
                    segs.append((p1, p2, max(dx, dy)))

    ratios = []
    for val, r in dims:
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        best = None
        best_d = 18.0
        for p1, p2, length in segs:
            mx, my = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
            dd = math.hypot(mx - cx, my - cy)
            if dd < best_d:
                best_d = dd
                best = length
        if best:
            ratios.append(best / val)

    if len(ratios) < 5:
        return None
    med = statistics.median(ratios)
    consistent = [r for r in ratios if abs(r - med) / med < 0.05]
    # Si las cotas no son consistentes entre sí, no confiar.
    if len(consistent) < max(5, len(ratios) // 2):
        return None
    return med


def _extract_page(page, px_per_m: float, pt2px: float) -> dict[str, list]:
    """type -> lista de (points_px, subtype|None, length_m|None), espacio sin rotar."""
    out: dict[str, list] = defaultdict(list)
    opening_paths = []
    stair_paths = []

    for d in page.get_drawings():
        typ = _classify_layer(d.get("layer") or "")
        if typ is None:
            continue
        if typ == "opening":
            opening_paths.append(d)
            continue
        if typ == "escalera":
            stair_paths.append(d)
            continue
        for poly in _path_polylines(d):
            if typ == "wall":
                for a, b in zip(poly, poly[1:]):
                    length_m = math.hypot(b[0] - a[0], b[1] - a[1]) * pt2px / px_per_m
                    if length_m >= _MIN_WALL_SEG_M:
                        out["wall_seg"].append((
                            [a[0] * pt2px, a[1] * pt2px, b[0] * pt2px, b[1] * pt2px],
                            None, length_m,
                        ))
            else:
                total_m = sum(
                    math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly, poly[1:])
                ) * pt2px / px_per_m
                if total_m < _MIN_LINE_M:
                    continue
                flat: list[float] = []
                for p in poly:
                    flat.extend([p[0] * pt2px, p[1] * pt2px])
                out[typ].append((flat, None, total_m))

    # Aberturas: agrupar paths cercanos en símbolos (union-find por bbox).
    tol_pt = _OPENING_CLUSTER_GAP_M * px_per_m / pt2px
    items = []
    for d in opening_paths:
        r = d["rect"]
        has_curve = any(it[0] == "c" for it in d["items"])
        items.append((r.x0, r.y0, r.x1, r.y1, has_curve))
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if (a[0] - tol_pt <= b[2] and b[0] - tol_pt <= a[2]
                    and a[1] - tol_pt <= b[3] and b[1] - tol_pt <= a[3]):
                parent[find(i)] = find(j)

    clusters: dict[int, list] = defaultdict(list)
    for i in range(len(items)):
        clusters[find(i)].append(items[i])
    for members in clusters.values():
        x0 = min(m[0] for m in members)
        y0 = min(m[1] for m in members)
        x1 = max(m[2] for m in members)
        y1 = max(m[3] for m in members)
        w_m = (x1 - x0) * pt2px / px_per_m
        h_m = (y1 - y0) * pt2px / px_per_m
        major = max(w_m, h_m)
        if major < _OPENING_MIN_M or major > _OPENING_MAX_M:
            continue
        has_curve = any(m[4] for m in members)
        cx, cy = (x0 + x1) / 2 * pt2px, (y0 + y1) / 2 * pt2px
        half = major / 2 * px_per_m
        pts = [cx - half, cy, cx + half, cy] if w_m >= h_m else [cx, cy - half, cx, cy + half]
        out["opening"].append((pts, "door" if has_curve else "window", None))

    # Escaleras: agrupar trazos cercanos (0.4 m) → un polígono bbox por escalera.
    s_tol = 0.4 * px_per_m / pt2px
    s_items = [(d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1) for d in stair_paths]
    s_parent = list(range(len(s_items)))

    def s_find(i: int) -> int:
        while s_parent[i] != i:
            s_parent[i] = s_parent[s_parent[i]]
            i = s_parent[i]
        return i

    for i in range(len(s_items)):
        for j in range(i + 1, len(s_items)):
            a, b = s_items[i], s_items[j]
            if (a[0] - s_tol <= b[2] and b[0] - s_tol <= a[2]
                    and a[1] - s_tol <= b[3] and b[1] - s_tol <= a[3]):
                s_parent[s_find(i)] = s_find(j)

    s_clusters: dict[int, list] = defaultdict(list)
    for i in range(len(s_items)):
        s_clusters[s_find(i)].append(s_items[i])
    for members in s_clusters.values():
        x0 = min(m[0] for m in members) * pt2px
        y0 = min(m[1] for m in members) * pt2px
        x1 = max(m[2] for m in members) * pt2px
        y1 = max(m[3] for m in members) * pt2px
        w_m = (x1 - x0) / px_per_m
        h_m = (y1 - y0) / px_per_m
        area = w_m * h_m
        if area < 1.0 or area > 25.0 or max(w_m, h_m) > 8.0:
            continue
        out["escalera"].append((
            [x0, y0, x1, y0, x1, y1, x0, y1], None, area,
        ))

    return out


def _rotate(res: dict[str, list], page, pt2px: float) -> dict[str, list]:
    """Pasa la geometría del espacio sin rotar al espacio visible de la página.
    get_drawings() ignora /Rotate; el raster que ve el usuario no."""
    import fitz

    if page.rotation == 0:
        return res
    rot = page.rotation_matrix
    out: dict[str, list] = defaultdict(list)
    for typ, entries in res.items():
        for flat, sub, length_m in entries:
            new: list[float] = []
            for x, y in zip(flat[0::2], flat[1::2]):
                p = fitz.Point(x / pt2px, y / pt2px) * rot
                new.extend([p.x * pt2px, p.y * pt2px])
            out[typ].append((new, sub, length_m))
    return out


def try_vector_import(plan_id: int) -> None:
    """Background task post-upload: si el PDF trae capas CAD, crea los
    elementos exactos y ajusta las escalas. Nunca lanza; loguea y sale."""
    try:
        _vector_import(plan_id)
    except Exception:  # noqa: BLE001
        logger.exception("vector import fallo plan=%s (flujo normal sigue)", plan_id)


def _vector_import(plan_id: int) -> None:
    import fitz

    from app.core.database import SessionLocal
    from app.models import DetectedElement, Plan
    from app.services.dxf_import import _bridge_walls_over_openings, _merge_segments

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None or not str(plan.pdf_path).lower().endswith(".pdf"):
            return
        pdf_path = Path(plan.pdf_path)
        if not pdf_path.exists():
            return
        dpi = plan.dpi or 150
        pt2px = dpi / 72.0

        doc = fitz.open(str(pdf_path))

        # ¿Hay capas de muros reconocibles? Si no, no es un PDF vectorial útil.
        wall_paths = 0
        for page in doc:
            for d in page.get_drawings():
                if _classify_layer(d.get("layer") or "") == "wall":
                    wall_paths += 1
            if wall_paths >= 20:
                break
        if wall_paths < 20:
            logger.info("vector import skip plan=%s: sin capas de muros", plan_id)
            return

        # Escala por página desde cotas; fallback a la primera página con cotas.
        base_ptm = None
        for page in doc:
            base_ptm = page_scale_pt_per_m(page)
            if base_ptm:
                break
        if not base_ptm:
            logger.info("vector import skip plan=%s: sin cotas legibles", plan_id)
            return

        page_scales = dict(plan.page_scales or {})
        totals = {"wall": 0, "opening": 0, "cloaca": 0, "electricidad": 0, "escalera": 0}

        for i in range(doc.page_count):
            pageno = i + 1
            page = doc[i]
            ptm = page_scale_pt_per_m(page) or base_ptm
            px_per_m = round(ptm * pt2px, 4)
            page_scales[str(pageno)] = px_per_m

            res = _rotate(_extract_page(page, px_per_m, pt2px), page, pt2px)

            # Gate por disciplina: cada lámina aporta solo los tipos de su
            # rótulo. Los muros de una lámina de cloaca/vigas/techos son xref
            # de fondo (duplicados de la arquitectura) y se descartan.
            allowed = _page_allowed_types(page)

            opening_els = [
                DetectedElement(
                    plan_id=plan.id, page=pageno, type="opening",
                    geometry={"points": [round(v, 2) for v in pts], "subtype": sub or "door"},
                    source="dxf",
                )
                for pts, sub, _ in res.get("opening", [])
            ] if "opening" in allowed else []

            walls = [
                DetectedElement(
                    plan_id=plan.id, page=pageno, type="wall",
                    geometry={"points": [round(v, 2) for v in pts]},
                    length_m=round(length_m, 3), height_m=2.8, source="dxf",
                )
                for pts, _, length_m in res.get("wall_seg", [])
            ] if "wall" in allowed else []
            merged = _merge_segments(walls, px_per_m)
            # Muro continuo sobre cada vano con abertura; el cómputo resta
            # las medidas de la abertura después (dintel/antepecho incluidos).
            merged = _bridge_walls_over_openings(merged, opening_els, px_per_m)
            for el in merged:
                el.height_m = 2.8
            db.add_all(merged)
            totals["wall"] += len(merged)

            db.add_all(opening_els)
            totals["opening"] += len(opening_els)

            for typ in ("cloaca", "electricidad"):
                if typ not in allowed:
                    continue
                for flat, _, length_m in res.get(typ, []):
                    db.add(DetectedElement(
                        plan_id=plan.id, page=pageno, type=typ,
                        geometry={"points": [round(v, 2) for v in flat]},
                        length_m=round(length_m, 3), source="dxf",
                    ))
                    totals[typ] += 1

            if "escalera" in allowed:
                for flat, _, area in res.get("escalera", []):
                    db.add(DetectedElement(
                        plan_id=plan.id, page=pageno, type="escalera",
                        geometry={"points": [round(v, 2) for v in flat]},
                        area_m2=round(area, 2), height_m=2.8, source="dxf",
                    ))
                    totals["escalera"] += 1

        plan.page_scales = page_scales
        plan.scale_px_per_m = page_scales.get("1")
        plan.scale_source = "vector"

        # Recintos: el CAD casi nunca trae una capa de ambientes, pero se
        # derivan geométricamente del área cerrada entre los muros importados.
        try:
            from app.services.room_derivation import derive_rooms_for_plan

            db.flush()
            rooms_created = derive_rooms_for_plan(plan_id, db)
            if rooms_created:
                totals["room"] = rooms_created
        except Exception:  # noqa: BLE001
            logger.exception("derivación de recintos falló plan=%s (import sigue)", plan_id)

        db.commit()
        logger.info("vector import ok plan=%s: %s", plan_id, totals)
