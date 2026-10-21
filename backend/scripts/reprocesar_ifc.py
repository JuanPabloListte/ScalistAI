"""Re-ejecuta el import IFC de uno o varios planos, en forma sincrónica.

Sirve para que planos ya importados tomen las mejoras del parser (sección de
vigas, viguetas, losas de entrepiso). `process_ifc` reemplaza los elementos del
plan en una sola transacción: no duplica. Ojo: se pierden las recetas
asignadas A MANO a elementos de ese plano (se recalculan las automáticas por
material).

Uso (desde el contenedor backend):
    python -m scripts.reprocesar_ifc --plan 123
    python -m scripts.reprocesar_ifc --project 45      # todos sus planos .ifc
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement
from app.models.plan import Plan
from app.services.ifc_import import process_ifc


def _plan_ids(plan_id: int | None, project_id: int | None) -> list[int]:
    with SessionLocal() as db:
        if plan_id is not None:
            plan = db.get(Plan, plan_id)
            if plan is None:
                print(f"No existe el plano {plan_id}")
                return []
            if not plan.pdf_path.lower().endswith(".ifc"):
                print(f"El plano {plan_id} no es un IFC ({plan.original_filename})")
                return []
            return [plan_id]
        ids = db.scalars(
            select(Plan.id)
            .where(Plan.project_id == project_id, func.lower(Plan.pdf_path).like("%.ifc"))
            .order_by(Plan.id)
        ).all()
        if not ids:
            print(f"El proyecto {project_id} no tiene planos IFC")
        return list(ids)


def _counts(plan_id: int) -> Counter:
    with SessionLocal() as db:
        rows = db.execute(
            select(DetectedElement.type, func.count())
            .where(DetectedElement.plan_id == plan_id)
            .group_by(DetectedElement.type)
        ).all()
    return Counter({t: n for t, n in rows})


def main(plan_id: int | None, project_id: int | None) -> int:
    ids = _plan_ids(plan_id, project_id)
    if not ids:
        return 1
    failed = 0
    for pid in ids:
        print(f"Plano {pid}: reprocesando…", flush=True)
        try:
            process_ifc(pid)
        except Exception as exc:  # noqa: BLE001 — process_ifc ya dejó el plano en error
            failed += 1
            print(f"  ERROR: {exc}")
            continue
        counts = _counts(pid)
        print(f"  {sum(counts.values())} elementos")
        for t, n in sorted(counts.items()):
            print(f"    {t:<16} {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Reprocesa planos IFC (reemplaza sus elementos).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", type=int, help="id del plano")
    g.add_argument("--project", type=int, help="id del proyecto (todos sus planos IFC)")
    a = p.parse_args()
    sys.exit(main(a.plan, a.project))
