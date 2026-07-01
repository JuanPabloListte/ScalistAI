"""Backfill del catálogo de entidades constructivas (Fase 0).

Crea una `ConstructionEntity` por cada `applies_to` que usen los assemblies de
la org, linkea cada assembly a su entidad y marca un default por entidad. Es
**idempotente**: matchea entidades por (org, type) y re-linkea sin duplicar.

La unidad de cada entidad sale del contrato de medición del dominio
(`cost_intelligence.domain.measurement.unit_for`) → una sola fuente de verdad.

Uso:
    python -m scripts.seed_construction_entities            # todas las orgs
    python -m scripts.seed_construction_entities --org 1
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from sqlalchemy import select

from app.core.database import SessionLocal
from app.cost_intelligence.domain.measurement import unit_for
from app.models.construction_entity import ConstructionEntity
from app.models.material import Assembly

# applies_to -> nombre amigable de la entidad constructiva.
_NAMES: dict[str, str] = {
    "wall": "Muro",
    "room_floor": "Piso / Solado",
    "room_wall": "Revoque de recinto",
    "room_perimeter": "Zócalo / Perímetro",
    "opening": "Abertura",
    "opening_perimeter": "Perímetro de abertura",
    "beam": "Viga",
    "column": "Columna",
    "roof": "Techo / Losa",
    "riostra": "Riostra / Viga de fundación",
    "cloaca": "Cloaca / Desagüe",
    "electricidad": "Instalación eléctrica",
    "escalera": "Escalera",
    "pozo": "Pozo / Zapata",
}


def seed_org(db, org_id: int) -> None:
    assemblies = db.scalars(
        select(Assembly).where(Assembly.organization_id == org_id)
    ).all()
    if not assemblies:
        print(f"  org {org_id}: sin assemblies, salteada")
        return

    # entidades existentes de la org, indexadas por type (= applies_to)
    existing = {
        e.type: e
        for e in db.scalars(
            select(ConstructionEntity).where(ConstructionEntity.organization_id == org_id)
        ).all()
    }

    by_applies: dict[str, list[Assembly]] = defaultdict(list)
    for a in assemblies:
        by_applies[a.applies_to].append(a)

    created = linked = 0
    for applies_to, recipes in sorted(by_applies.items()):
        entity = existing.get(applies_to)
        if entity is None:
            entity = ConstructionEntity(
                organization_id=org_id,
                name=_NAMES.get(applies_to, applies_to.replace("_", " ").title()),
                type=applies_to,
                unit=unit_for(applies_to) or "m2",
            )
            db.add(entity)
            db.flush()  # asigna id para el FK
            existing[applies_to] = entity
            created += 1

        for r in recipes:
            if r.construction_entity_id != entity.id:
                r.construction_entity_id = entity.id
                linked += 1
        # default: si ninguna alternativa está marcada, la primera es default
        if not any(r.is_default_alternative for r in recipes):
            recipes[0].is_default_alternative = True

        print(f"    [{applies_to:16s}] {entity.name:28s} ({entity.unit}) "
              f"— {len(recipes)} receta(s)")

    db.commit()
    print(f"  org {org_id}: {created} entidades nuevas, {linked} assemblies linkeados")


def run(org_id: int | None) -> None:
    with SessionLocal() as db:
        if org_id is not None:
            orgs = [org_id]
        else:
            orgs = sorted({a.organization_id for a in db.scalars(select(Assembly)).all()})
        print(f"seeding entidades constructivas en {len(orgs)} org(s)")
        for oid in orgs:
            seed_org(db, oid)
    print("OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--org", type=int, default=None)
    args = p.parse_args()
    run(args.org)
    return 0


if __name__ == "__main__":
    sys.exit(main())
