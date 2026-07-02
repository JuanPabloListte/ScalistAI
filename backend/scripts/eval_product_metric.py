"""Métrica de PRODUCTO del detector ML: F1 de elementos extraídos.

El mIoU por píxel no mide lo que el producto necesita: "¿el modelo encontró
ESTE muro, con una geometría utilizable?". Este script evalúa el modelo activo
contra un SET DORADO de páginas reales cuyos elementos ya fueron aprobados en
la app (source dxf/manual = ground truth del producto, no anotación extra).

Definiciones (cobertura geométrica, sin emparejamiento 1:1):
  - precision: fracción de predicciones cubiertas >=50% por la máscara del GT
    de su tipo (la predicción "cae donde hay algo real").
  - recall: fracción de elementos GT cubiertos >=50% por la máscara de las
    predicciones (el elemento real "fue encontrado").
  - F1 = armónica. Se reporta además el ratio de metros lineales de muro
    (pred/GT) porque el presupuesto computa longitudes, no píxeles.

El matching reutiliza la geometría de hybrid_validation (misma máscara con
buffer y cobertura que usa el modo híbrido en producción).

Uso:
    python -m scripts.eval_product_metric --init      # congela el set dorado
    python -m scripts.eval_product_metric             # evalúa el modelo activo

Salida: storage/models/product_eval/<version>_<fecha>.json + tabla por consola.
El set dorado queda CONGELADO en storage/models/golden_set.json: todas las
versiones futuras comparan contra las mismas páginas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

GOLDEN_FILE = Path("storage/models/golden_set.json")
OUT_DIR = Path("storage/models/product_eval")

# Tipos que el detector ML predice y cómo se matchean.
_MASK_TYPES = ("wall", "room", "beam", "column", "escalera", "roof")
_OPENING_MATCH_M = 0.6
_COVERAGE_THRESHOLD = 0.5


# ----------------------------------------------------------------------
# Set dorado
# ----------------------------------------------------------------------
def init_golden_set(max_pages: int, per_plan: int) -> int:
    """Elige páginas reales con GT aprobado y las congela."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.detected_element import DetectedElement
    from app.models.plan import Plan

    if GOLDEN_FILE.exists():
        print(f"Ya existe {GOLDEN_FILE} — borralo a mano si querés regenerarlo "
              f"(rompe la comparabilidad histórica).")
        return 1

    with SessionLocal() as db:
        plans = {p.id: p for p in db.scalars(select(Plan)).all()}
        # Conteo por (plan, page, type) de elementos aprobados.
        counts: dict[tuple[int, int], dict[str, int]] = {}
        for el in db.scalars(select(DetectedElement).where(
                DetectedElement.is_candidate.is_(False))):
            plan = plans.get(el.plan_id)
            if plan is None or (plan.pdf_path or "").lower().endswith(".ifc"):
                continue  # IFC no tiene raster: fuera del alcance del ML
            key = (el.plan_id, el.page)
            counts.setdefault(key, {}).setdefault(el.type, 0)
            counts[key][el.type] += 1

        candidates = []
        for (plan_id, page), by_type in counts.items():
            plan = plans[plan_id]
            scales = plan.page_scales or {}
            if str(page) not in scales:
                continue  # sin escala no se puede evaluar en metros
            if by_type.get("wall", 0) < 8:
                continue  # páginas con poca arquitectura no discriminan
            diversity = len([t for t in by_type if t in _MASK_TYPES or t == "opening"])
            candidates.append({
                "plan_id": plan_id, "page": page,
                "n_elements": sum(by_type.values()),
                "types": by_type, "diversity": diversity,
            })

        # Diversidad primero; cap por plan para no sesgar a un solo estudio.
        candidates.sort(key=lambda c: (-c["diversity"], -c["n_elements"]))
        chosen, seen_per_plan = [], {}
        for c in candidates:
            if seen_per_plan.get(c["plan_id"], 0) >= per_plan:
                continue
            chosen.append(c)
            seen_per_plan[c["plan_id"]] = seen_per_plan.get(c["plan_id"], 0) + 1
            if len(chosen) >= max_pages:
                break

    if len(chosen) < 3:
        print(f"ERROR: solo {len(chosen)} páginas elegibles (mínimo 3).")
        return 2

    GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FILE.write_text(json.dumps({
        "pages": chosen,
        "frozen_at": dt.datetime.now(dt.UTC).isoformat(),
        "criteria": "aprobados, >=8 muros, con escala, cap por plan",
    }, indent=2, ensure_ascii=False))
    print(f"Set dorado congelado: {len(chosen)} páginas de "
          f"{len(seen_per_plan)} planos → {GOLDEN_FILE}")
    for c in chosen:
        print(f"  plan {c['plan_id']:>3} pág {c['page']:>2}  "
              f"{c['n_elements']:>4} elementos  tipos={sorted(c['types'])}")
    return 0


# ----------------------------------------------------------------------
# Matching geométrico (reutiliza hybrid_validation)
# ----------------------------------------------------------------------
def _match_mask_type(gt_els, preds, el_type, px_per_m, w, h):
    """(tp_pred, n_pred, tp_gt, n_gt) por cobertura de máscara bidireccional."""
    from app.services.hybrid_validation import _build_vector_mask, _candidate_coverage

    n_pred, n_gt = len(preds), len(gt_els)
    if n_pred == 0 and n_gt == 0:
        return 0, 0, 0, 0

    tp_pred = 0
    if n_pred and n_gt:
        gt_mask, ds = _build_vector_mask(gt_els, el_type, px_per_m, w, h)
        if gt_mask is not None:
            for p in preds:
                cov = _candidate_coverage(gt_mask, ds, p.get("geometry") or {}, el_type)
                if cov >= _COVERAGE_THRESHOLD:
                    tp_pred += 1

    tp_gt = 0
    if n_gt and n_pred:
        wrapped = [SimpleNamespace(geometry=p.get("geometry") or {}) for p in preds]
        pred_mask, ds = _build_vector_mask(wrapped, el_type, px_per_m, w, h)
        if pred_mask is not None:
            for g in gt_els:
                cov = _candidate_coverage(pred_mask, ds, g.geometry or {}, el_type)
                if cov >= _COVERAGE_THRESHOLD:
                    tp_gt += 1
    return tp_pred, n_pred, tp_gt, n_gt


def _match_openings(gt_els, preds, px_per_m):
    """Matching bipartito greedy por distancia entre centros (<=0.6 m)."""
    def _center(geometry):
        pts = (geometry or {}).get("points") or []
        xy = list(zip(pts[0::2], pts[1::2]))
        if not xy:
            return None
        return (sum(p[0] for p in xy) / len(xy), sum(p[1] for p in xy) / len(xy))

    gt_centers = [c for c in (_center(g.geometry) for g in gt_els) if c]
    pred_centers = []
    for p in preds:
        try:
            pred_centers.append((float(p["cx"]), float(p["cy"])))
        except (KeyError, TypeError, ValueError):
            continue

    max_px = _OPENING_MATCH_M * px_per_m
    dists = sorted(
        (math.hypot(px - gx, py - gy), i, j)
        for i, (px, py) in enumerate(pred_centers)
        for j, (gx, gy) in enumerate(gt_centers)
    )
    used_p, used_g = set(), set()
    matches = 0
    for d, i, j in dists:
        if d > max_px:
            break
        if i in used_p or j in used_g:
            continue
        used_p.add(i); used_g.add(j); matches += 1
    return matches, len(pred_centers), matches, len(gt_centers)


# ----------------------------------------------------------------------
# Evaluación
# ----------------------------------------------------------------------
def evaluate() -> int:
    import cv2
    import numpy as np
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.detected_element import DetectedElement
    from app.models.plan import Plan
    from app.services.ml_detector import get_ml_detector
    from app.services.pdf import rasterize

    if not GOLDEN_FILE.exists():
        print("No hay set dorado. Corré primero: python -m scripts.eval_product_metric --init")
        return 1
    golden = json.loads(GOLDEN_FILE.read_text())["pages"]

    detector = get_ml_detector()
    if not detector.is_available():
        print("ERROR: modelo ML no disponible.")
        return 2
    info = detector.model_info()
    if "version" not in info:  # model_info no siempre expone la versión
        try:
            info["version"] = json.loads(
                Path("storage/models/active.json").read_text()).get("version", "?")
        except Exception:  # noqa: BLE001
            info["version"] = "?"

    # Acumuladores micro (sumar TP/FP/FN sobre todas las páginas).
    agg: dict[str, dict[str, int]] = {}
    wall_ml = {"pred": 0.0, "gt": 0.0}
    pages_ok = 0

    # candidato ML por tipo → atributo del MLDetectionResult
    result_attr = {"wall": "walls", "room": "rooms", "beam": "beams",
                   "column": "columns", "escalera": "escaleras", "roof": "roofs"}

    with SessionLocal() as db:
        for entry in golden:
            plan = db.get(Plan, entry["plan_id"])
            if plan is None:
                print(f"  SKIP plan {entry['plan_id']}: ya no existe")
                continue
            page = entry["page"]
            px_per_m = float((plan.page_scales or {}).get(str(page), 0) or 0)
            if px_per_m <= 0:
                print(f"  SKIP plan {plan.id} pág {page}: sin escala")
                continue
            try:
                png = rasterize(plan.pdf_path, page - 1, plan.dpi or 150)
                img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            except Exception as exc:  # noqa: BLE001
                print(f"  SKIP plan {plan.id} pág {page}: raster falló ({exc})")
                continue

            gt = list(db.scalars(select(DetectedElement).where(
                DetectedElement.plan_id == plan.id,
                DetectedElement.page == page,
                DetectedElement.is_candidate.is_(False))))
            res = detector.detect(img, px_per_m, page - 1)
            h, w = img.shape[:2]
            pages_ok += 1

            for el_type, attr in result_attr.items():
                gt_t = [g for g in gt if g.type == el_type]
                preds = getattr(res, attr)
                tp_p, n_p, tp_g, n_g = _match_mask_type(
                    gt_t, preds, el_type, px_per_m, w, h)
                a = agg.setdefault(el_type, {"tp_pred": 0, "n_pred": 0, "tp_gt": 0, "n_gt": 0})
                a["tp_pred"] += tp_p; a["n_pred"] += n_p
                a["tp_gt"] += tp_g; a["n_gt"] += n_g
                if el_type == "wall":
                    wall_ml["gt"] += sum(g.length_m or 0 for g in gt_t)
                    wall_ml["pred"] += sum(p.get("length_m") or 0 for p in preds)

            gt_open = [g for g in gt if g.type in ("opening", "door", "window", "sliding_door")]
            tp_p, n_p, tp_g, n_g = _match_openings(gt_open, res.openings, px_per_m)
            a = agg.setdefault("opening", {"tp_pred": 0, "n_pred": 0, "tp_gt": 0, "n_gt": 0})
            a["tp_pred"] += tp_p; a["n_pred"] += n_p
            a["tp_gt"] += tp_g; a["n_gt"] += n_g

            print(f"  plan {plan.id:>3} pág {page:>2}: GT={len(gt):>4} "
                  f"preds: walls={len(res.walls)} rooms={len(res.rooms)} "
                  f"openings={len(res.openings)}")

    # Reporte.
    rows = []
    for el_type, a in sorted(agg.items()):
        if a["n_pred"] == 0 and a["n_gt"] == 0:
            continue
        prec = a["tp_pred"] / a["n_pred"] if a["n_pred"] else 0.0
        rec = a["tp_gt"] / a["n_gt"] if a["n_gt"] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        rows.append({"type": el_type, "precision": round(prec, 3),
                     "recall": round(rec, 3), "f1": round(f1, 3),
                     "n_pred": a["n_pred"], "n_gt": a["n_gt"]})

    print()
    print(f"{'tipo':<12} {'prec':>6} {'rec':>6} {'F1':>6} {'preds':>7} {'GT':>6}")
    print("-" * 48)
    for r in rows:
        print(f"{r['type']:<12} {r['precision']:>6.3f} {r['recall']:>6.3f} "
              f"{r['f1']:>6.3f} {r['n_pred']:>7} {r['n_gt']:>6}")
    ml_ratio = (wall_ml["pred"] / wall_ml["gt"]) if wall_ml["gt"] else None
    if ml_ratio is not None:
        print(f"\nmuro_ml pred/GT = {ml_ratio:.2f}  "
              f"({wall_ml['pred']:.0f} ml pred vs {wall_ml['gt']:.0f} ml GT)")
    macro_f1 = sum(r["f1"] for r in rows) / len(rows) if rows else 0.0
    print(f"macro-F1 = {macro_f1:.3f}  ({pages_ok} páginas)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"v{info.get('version', '?')}_{stamp}.json"
    out.write_text(json.dumps({
        "model": info, "pages_evaluated": pages_ok,
        "per_class": rows, "macro_f1": round(macro_f1, 4),
        "wall_ml_ratio": round(ml_ratio, 4) if ml_ratio is not None else None,
        "evaluated_at": dt.datetime.now(dt.UTC).isoformat(),
    }, indent=2, ensure_ascii=False))
    print(f"\nguardado: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Métrica de producto del detector ML.")
    parser.add_argument("--init", action="store_true", help="Congela el set dorado")
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--per-plan", type=int, default=2,
                        help="Máx páginas por plano (diversidad entre estudios)")
    args = parser.parse_args()
    if args.init:
        return init_golden_set(args.max_pages, args.per_plan)
    return evaluate()


if __name__ == "__main__":
    sys.exit(main())
