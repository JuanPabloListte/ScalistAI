"""Siembra la biblioteca de assemblies (recetas constructivas) por defecto.

Una `Assembly` es una receta: "1 m² de muro de ladrillo hueco 18 consume 16
ladrillos + 0.20 bolsa de cemento + ...". El motor de cómputo
(`_get_materials_summary_data`) multiplica la geometría exacta extraída del
DXF/PDF por estas recetas → lista de materiales + presupuesto. Sin recetas el
cómputo da vacío (la geometría está, pero no sabe en qué materiales se traduce).

Consumos = estimaciones estándar de construcción argentina; el usuario los
ajusta. `applies_to` define a qué tipo de elemento aplica (wall, room_floor,
room_perimeter, opening, beam, column, roof).

Uso:
    python -m scripts.seed_assemblies --org 1
    python -m scripts.seed_assemblies --org 1 --apply-to-plan 82
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement
from app.models.material import Assembly, AssemblyMaterial, Material

# Etapas de obra estándar (orden constructivo). Agrupan el cómputo para el
# cronograma (Gantt) y la certificación de avance.
FUNDACION, ESTRUCTURA, MAMPOSTERIA, INSTALACIONES, TERMINACIONES = (
    ("Fundación", 1), ("Estructura", 2), ("Mampostería", 3),
    ("Instalaciones", 4), ("Terminaciones", 5),
)

# (nombre, applies_to, rendimiento_diario, etapa) -> [(material_id, consumo, desperdicio)]
# material_id refiere a la tabla materials de la organización.
RECIPES: dict[tuple[str, str, float, tuple[str, int]], list[tuple[int, float, float]]] = {
    ("Columna H°A° 20x20", "column", 4.0, ESTRUCTURA): [
        (6, 20.0, 0.10), (9, 30.0, 0.05), (13, 8.0, 0.0),
    ],
    ("Muro Ladrillo Hueco 18x18x33", "wall", 12.0, MAMPOSTERIA): [
        (1, 16.0, 0.05),   # ladrillo hueco 18 (un/m²)
        (6, 0.20, 0.10),   # cemento (bolsa/m²)
        (7, 0.03, 0.10),   # arena (m³/m²)
        (13, 1.3, 0.0),    # mano de obra ayudante (hs/m²)
    ],
    ("Contrapiso y Carpeta", "room_floor", 40.0, TERMINACIONES): [
        (6, 0.30, 0.10), (7, 0.09, 0.10), (13, 0.6, 0.0),
    ],
    ("Piso Porcelanato 60x60", "room_floor", 20.0, TERMINACIONES): [
        (3, 1.0, 0.10), (6, 0.12, 0.10), (13, 0.9, 0.0),
    ],
}

# Asignación por defecto tipo de elemento → applies_to de la receta.
_TYPE_TO_APPLIES = {"wall": "wall", "room": "room_floor", "column": "column"}


def seed(org_id: int, apply_to_plan: int | None) -> None:
    db = SessionLocal()
    try:
        mats = {m.id for m in db.scalars(
            select(Material).where(Material.organization_id == org_id)).all()}
        if not mats:
            print(f"ERROR: la org {org_id} no tiene materiales cargados.")
            return

        # Idempotente: borra las assemblies previas de la org y recrea.
        for a in db.scalars(select(Assembly).where(Assembly.organization_id == org_id)).all():
            db.delete(a)
        db.flush()

        by_applies: dict[str, list[Assembly]] = {}
        for (name, applies_to, yield_, (stage, stage_order)), lines in RECIPES.items():
            a = Assembly(organization_id=org_id, name=name,
                         applies_to=applies_to, daily_yield=yield_,
                         stage=stage, stage_order=stage_order)
            db.add(a)
            db.flush()
            for mat_id, cons, waste in lines:
                if mat_id not in mats:
                    print(f"  AVISO: material {mat_id} no existe en org {org_id}, salteado")
                    continue
                db.add(AssemblyMaterial(assembly_id=a.id, material_id=mat_id,
                                        consumption=cons, waste_factor=waste))
            by_applies.setdefault(applies_to, []).append(a)
            print(f"  + {name} ({applies_to})")
        db.flush()

        if apply_to_plan is not None:
            els = db.scalars(select(DetectedElement).where(
                DetectedElement.plan_id == apply_to_plan,
                DetectedElement.is_candidate.is_(False))).all()
            n = 0
            for el in els:
                applies = _TYPE_TO_APPLIES.get(el.type)
                if applies and applies in by_applies:
                    el.assemblies = list(by_applies[applies])
                    n += 1
            print(f"asignadas recetas por defecto a {n} elementos del plan {apply_to_plan}")

        db.commit()
        print("OK")
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--org", type=int, required=True)
    p.add_argument("--apply-to-plan", type=int, default=None,
                   help="Asigna las recetas por defecto a los elementos de ese plan")
    args = p.parse_args()
    seed(args.org, args.apply_to_plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
