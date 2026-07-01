"""Backfill del histórico de precios (Fase 1a).

Crea un punto inicial por cada material desde su `unit_price` actual
(source='backfill'). Idempotente: saltea materiales que ya tienen histórico.
Ejercita el caso de uso + repo SQL (no escribe SQL a mano).

Uso:
    python -m scripts.seed_price_history            # todos los materiales
    python -m scripts.seed_price_history --org 1
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice
from app.cost_intelligence.infrastructure.persistence.price_repository import SqlPriceHistoryRepository
from app.models.material import Material


def run(org_id: int | None) -> None:
    with SessionLocal() as db:
        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)
        stmt = select(Material)
        if org_id is not None:
            stmt = stmt.where(Material.organization_id == org_id)
        materials = db.scalars(stmt).all()

        created = skipped = 0
        for m in materials:
            if repo.has_history(m.id):
                skipped += 1
                continue
            record.execute(m.id, m.unit_price or 0.0, source="backfill", observed_on=date.today())
            created += 1
        db.commit()
        print(f"backfill precios: {created} creados, {skipped} ya tenían histórico "
              f"({len(materials)} materiales)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--org", type=int, default=None)
    run(p.parse_args().org)
    return 0


if __name__ == "__main__":
    sys.exit(main())
