"""Ingesta un relevamiento de mercado curado (backend/data/market_survey_*.json).

El JSON es el registro AUDITABLE completo del relevamiento: producto comercial,
marca, proveedor, URL, unidad de venta, conversión a la unidad canónica,
confianza del matching y disponibilidad. Este script ingesta a
`material_price_history` SOLO los matches con confidence >= 0.80 y
needs_review == false; el resto se lista para revisión manual.

Reglas (mismas del motor de costos):
- NUNCA inventa precios: solo carga lo que está en el JSON con fuente y URL.
- Idempotente por (material, fecha, fuente): re-correr no duplica.
- `source` queda como "vendor — relevado AAAA-MM-DD" (la URL exacta vive en el
  JSON versionado en git).

Uso:
    python -m scripts.ingest_market_survey --file data/market_survey_2026-07.json --dry-run
    python -m scripts.ingest_market_survey --file data/market_survey_2026-07.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice
from app.cost_intelligence.infrastructure.persistence.price_repository import SqlPriceHistoryRepository
from app.models.material import Material

MIN_CONFIDENCE = 0.80


def run(path: Path, dry: bool) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    survey_date = date.fromisoformat(data["survey_date"])

    with SessionLocal() as db:
        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)
        ingested, review = 0, []

        for m in data.get("matches", []):
            mid = m.get("material_id")
            price = m.get("price_canonical")
            conf = float(m.get("confidence") or 0)
            if m.get("needs_review") or conf < MIN_CONFIDENCE or not price:
                review.append(m)
                continue

            mat = db.get(Material, mid)
            if mat is None:
                print(f"  AVISO: material {mid} no existe — salteado")
                continue

            source = f"{m['vendor']} — relevado {survey_date.isoformat()}"
            dup = db.execute(text(
                "select 1 from material_price_history "
                "where material_id=:i and date=:d and source=:s limit 1"
            ), {"i": mid, "d": survey_date, "s": source}).first()
            if dup:
                print(f"  = ya ingestado: {mat.name[:40]} (idempotencia)")
                continue

            print(f"  + {mat.name[:38]:<40} ${price:>12,.2f}/{mat.unit:<8} "
                  f"conf={conf:.0%}  {m.get('product', '')[:40]}")
            if not dry:
                record.execute(mid, price, source=source, observed_on=survey_date)
            ingested += 1

        if not dry:
            db.commit()

        print(f"\n{'[DRY-RUN] ' if dry else ''}{ingested} precios relevados ingestados "
              f"(fecha {survey_date}).")
        if review:
            print(f"\nREVISIÓN MANUAL REQUERIDA ({len(review)}):")
            for m in review:
                print(f"  ? {m.get('material_name', m.get('material_id'))}: "
                      f"{(m.get('note') or 'confianza ' + str(m.get('confidence')))[:90]}")
        return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default="data/market_survey_2026-07.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return run(Path(args.file), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
