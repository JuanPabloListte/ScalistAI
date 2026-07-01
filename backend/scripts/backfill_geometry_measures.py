"""Backfill de `length_m` / `area_m2` en `detected_elements` desde su geometría.

Problema: muchos elementos (sobre todo de planos importados de PDF) quedaron con
`length_m`/`area_m2` en None aunque su `geometry.points` SÍ contiene la forma
(segmento o polígono, en píxeles). Sin esos campos, el cómputo no mide:
- aberturas sin ancho -> carpintería NO se computa (¡el ítem más caro!)
- rooms sin perímetro  -> revoque interior y zócalo sub-computan

Fix: recuperar la medida desde los puntos × la escala px/m de la página
(`Plan.page_scales` / `scale_px_per_m`). Solo RELLENA nulos (no pisa lo medido).
Idempotente. NO inventa nada: usa geometría real ya guardada.

Uso:
    python -m scripts.backfill_geometry_measures --dry-run
    python -m scripts.backfill_geometry_measures
"""
from __future__ import annotations

import argparse
import math
import sys

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement as DE
from app.models.plan import Plan
from app.services.dxf_import import _PATH_TYPES, _POLYGON_TYPES, _SEGMENT_TYPES


def _coords(flat: list) -> list[tuple[float, float]]:
    return list(zip(flat[0::2], flat[1::2]))


def _polyline_len(flat: list) -> float:
    c = _coords(flat)
    return sum(math.dist(c[i], c[i + 1]) for i in range(len(c) - 1))


def _ring_perimeter(flat: list) -> float:
    c = _coords(flat)
    n = len(c)
    return sum(math.dist(c[i], c[(i + 1) % n]) for i in range(n))


def _ring_area(flat: list) -> float:
    c = _coords(flat)
    n = len(c)
    s = sum(c[i][0] * c[(i + 1) % n][1] - c[(i + 1) % n][0] * c[i][1] for i in range(n))
    return abs(s) / 2.0


def run(dry: bool) -> None:
    with SessionLocal() as db:
        fixed_len = fixed_area = skipped_noscale = 0
        for p in db.scalars(select(Plan)):
            scales = p.page_scales or {}
            els = db.scalars(select(DE).where(
                DE.plan_id == p.id,
                or_(DE.length_m.is_(None), DE.area_m2.is_(None)))).all()
            for el in els:
                g = el.geometry or {}
                flat = g.get("points")
                if not isinstance(flat, list) or len(flat) < 4:
                    continue
                sc = scales.get(str(el.page)) or p.scale_px_per_m
                if not sc or sc <= 0:
                    skipped_noscale += 1
                    continue
                if el.type in _POLYGON_TYPES:
                    if el.area_m2 is None and len(flat) >= 6:
                        if not dry:
                            el.area_m2 = round(_ring_area(flat) / (sc * sc), 2)
                        fixed_area += 1
                    if el.length_m is None and el.type in ("room", "roof") and len(flat) >= 6:
                        if not dry:
                            el.length_m = round(_ring_perimeter(flat) / sc, 2)
                        fixed_len += 1
                elif el.type in _SEGMENT_TYPES or el.type in _PATH_TYPES:
                    if el.length_m is None:
                        if not dry:
                            el.length_m = round(_polyline_len(flat) / sc, 2)
                        fixed_len += 1
        if not dry:
            db.commit()
        prefix = "[DRY-RUN] " if dry else ""
        print(f"{prefix}length_m rellenados={fixed_len} · area_m2 rellenados={fixed_area}"
              f" · sin escala (omitidos)={skipped_noscale}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
