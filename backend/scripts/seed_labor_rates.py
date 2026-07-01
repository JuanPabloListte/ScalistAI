"""Backfill de mano de obra first-class (Fase 1b).

Crea un `LaborRate` por cada material de categoría "Recursos Humanos" (la mano
de obra que hoy vive como Material), derivando el costo diario desde su precio:
si la unidad es "hs", costo_diario = precio_hora × 8. Idempotente: saltea
oficios ya existentes. NO toca el material (no-breaking).

No inventa oficios extra (Oficial/Capataz/…): esos los carga el usuario con sus
valores reales — la estructura queda lista.

Uso:
    python -m scripts.seed_labor_rates            # todas las orgs
    python -m scripts.seed_labor_rates --org 1
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_labor_rate import RecordLaborRate
from app.cost_intelligence.infrastructure.persistence.labor_repository import SqlLaborRateHistoryRepository
from app.models.labor import LaborRate
from app.models.material import Material

HOURS_PER_DAY = 8


def _trade_name(material_name: str) -> str:
    # "Mano de Obra Ayudante" -> "Ayudante"
    name = material_name.replace("Mano de Obra", "").replace("Mano de obra", "").strip()
    return name or material_name


def run(org_id: int | None) -> None:
    with SessionLocal() as db:
        repo = SqlLaborRateHistoryRepository(db)
        record = RecordLaborRate(repo)
        stmt = select(Material).where(Material.category == "Recursos Humanos")
        if org_id is not None:
            stmt = stmt.where(Material.organization_id == org_id)
        labor_materials = db.scalars(stmt).all()

        created = skipped = 0
        for m in labor_materials:
            trade = _trade_name(m.name)
            existing = db.scalars(select(LaborRate).where(
                LaborRate.organization_id == m.organization_id,
                LaborRate.trade == trade,
            )).first()
            if existing is not None:
                skipped += 1
                continue
            daily = (m.unit_price or 0.0) * (HOURS_PER_DAY if (m.unit or "").lower() == "hs"
                                             else 1)
            rate = LaborRate(organization_id=m.organization_id, trade=trade, daily_cost=0.0)
            db.add(rate)
            db.flush()  # asigna id
            record.execute(rate.id, daily, source="derivado-de-material",
                           observed_on=date.today())
            created += 1
            print(f"  + [{trade:20s}] ${daily:,.0f}/día  (de '{m.name}' {m.unit_price}/{m.unit})")
        db.commit()
        print(f"labor_rates: {created} oficios creados, {skipped} ya existían "
              f"({len(labor_materials)} materiales de mano de obra)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--org", type=int, default=None)
    run(p.parse_args().org)
    return 0


if __name__ == "__main__":
    sys.exit(main())
