"""Crea las recetas default que FALTABAN para las terminaciones interiores:
cielorraso (`room_ceiling`) y revoque + pintura interior de muros (`room_wall`).

Contexto: antes un `room` solo generaba el piso (contrapiso). Con la expansión
del measurement_provider (room -> floor + ceiling + wall) + estas recetas, cada
ambiente ahora computa también su cielorraso y el revoque/pintura de sus muros
interiores → el presupuesto deja de salir incompleto hacia arriba.

Coeficientes = ratios estándar de obra por m² (refinables por el usuario, que es
el experto). Materiales REALES del catálogo, con precio vigente. Idempotente.

Uso:  python -m scripts.seed_room_finishes
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.material import Assembly, AssemblyMaterial

ORG_ID = 1

# (applies_to, nombre, daily_yield m²/día, stage, stage_order,
#  [(material_id, consumo_por_m², waste_factor)])
RECIPES = [
    ("room_ceiling", "Cielorraso de yeso + Pintura", 15.0, "Terminaciones", 6, [
        (38, 0.30, 0.10),    # Yeso Proyectable 30kg
        (201, 0.04, 0.05),   # Látex interior (tacho ~20L, 2 manos)
        (13, 0.80, 0.00),    # Mano de Obra Ayudante (hs)
    ]),
    ("room_wall", "Revoque interior + Pintura", 12.0, "Terminaciones", 6, [
        (6, 0.08, 0.10),     # Cemento Loma Negra 50kg (jaharro)
        (36, 0.12, 0.10),    # Cal Hidratada 20kg
        (7, 0.02, 0.10),     # Arena Gruesa Lavada (m³)
        (40, 0.10, 0.05),    # Revoque Fino Interior Weber 25kg
        (201, 0.04, 0.05),   # Látex interior (tacho)
        (13, 0.90, 0.00),    # Mano de Obra Ayudante (hs)
    ]),
    ("room_perimeter", "Zócalo de porcelanato", 60.0, "Terminaciones", 6, [
        (3, 0.12, 0.10),     # Porcelanato 60x60 (tira de zócalo ~10cm) m²/ml
        (27, 0.02, 0.05),    # Pegamento/Pastina Porcelanato (bolsa)
        (13, 0.20, 0.00),    # Mano de Obra Ayudante (hs)
    ]),
]


def run() -> None:
    with SessionLocal() as db:
        for applies_to, name, dyield, stage, order, mats in RECIPES:
            exists = db.scalars(select(Assembly).where(
                Assembly.organization_id == ORG_ID,
                Assembly.applies_to == applies_to,
                Assembly.is_default_alternative.is_(True)).limit(1)).first()
            if exists:
                print(f"  (ya existe default {applies_to}: '{exists.name}')")
                continue
            a = Assembly(organization_id=ORG_ID, name=name, applies_to=applies_to,
                         daily_yield=dyield, stage=stage, stage_order=order,
                         is_default_alternative=True)
            db.add(a)
            db.flush()
            for mid, cons, waste in mats:
                db.add(AssemblyMaterial(assembly_id=a.id, material_id=mid,
                                        consumption=cons, waste_factor=waste))
            print(f"  [+] {applies_to}: '{name}'  ({len(mats)} materiales)")
        db.commit()
    print("listo.")


if __name__ == "__main__":
    sys.exit(run())
