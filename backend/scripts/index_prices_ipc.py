"""Actualiza precios desactualizados al presente por índice IPC (INDEC).

El problema: en Argentina un precio de 2022/2023/2025 no sirve en 2026. Muchos
insumos no se pueden re-relevar online (no todo corralón los publica), así que
la práctica estándar de cómputo es **actualizarlos por índice**.

Este script toma el ÚLTIMO precio conocido de cada material y lo lleva al mes
más reciente del IPC (INDEC) multiplicando por la inflación acumulada:

    precio_hoy = precio_viejo × (IPC_actual / IPC_a_la_fecha_del_precio)

HONESTO por diseño:
- Registra un punto nuevo con `source="IPC índice INDEC (base AAAA-MM)"`: NUNCA
  se confunde con un relevamiento real. En la UI se ve la fuente y la fecha.
- NO toca los materiales ya frescos (último precio >= último IPC).
- NO re-indexa lo ya indexado (no compone el índice sobre sí mismo).
- Un precio indexado es una ESTIMACIÓN por inflación, no un precio de plaza.
  El IPC es proxy: la construcción tiene su propia dinámica (el ICC de INDEC
  sería más fino pero está discontinuado en la API pública).

Requiere IPC cargado (scripts/fetch_indec_macro.py). Uso:
    python -m scripts.index_prices_ipc --dry-run       # muestra el impacto
    python -m scripts.index_prices_ipc                 # ingesta (org 1)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice
from app.cost_intelligence.infrastructure.persistence.price_repository import SqlPriceHistoryRepository
from app.models.material import Material

_INDEX_SOURCE_PREFIX = "IPC índice"


def _load_ipc(db) -> list[tuple[date, float]]:
    rows = db.execute(text(
        "select date, value from macro_series where indicator='IPC' order by date"
    )).all()
    return [(d.date() if hasattr(d, "date") else d, float(v)) for d, v in rows]


def _ipc_on_or_before(ipc: list[tuple[date, float]], target: date) -> tuple[date, float] | None:
    """Valor IPC del mes más reciente <= target (IPC es mensual)."""
    best = None
    for d, v in ipc:
        if d <= target:
            best = (d, v)
        else:
            break
    return best


def run(org_id: int, dry: bool) -> int:
    with SessionLocal() as db:
        ipc = _load_ipc(db)
        if len(ipc) < 2:
            print("ERROR: no hay IPC cargado. Corré scripts/fetch_indec_macro.py primero.")
            return 2
        ipc_now_date, ipc_now = ipc[-1]
        print(f"IPC de referencia: {ipc_now_date:%Y-%m} = {ipc_now:,.1f} (INDEC)\n")

        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)

        materials = db.scalars(
            select(Material).where(Material.organization_id == org_id)).all()

        indexed = skipped_fresh = skipped_indexed = skipped_nodata = 0
        rows_out: list[tuple] = []

        for m in materials:
            last = db.execute(text(
                "select date, price, source from material_price_history "
                "where material_id=:i order by date desc, id desc limit 1"
            ), {"i": m.id}).first()
            if last is None or float(last.price) <= 0:
                skipped_nodata += 1
                continue
            last_date = last.date.date() if hasattr(last.date, "date") else last.date
            last_price = float(last.price)

            if (last.source or "").startswith(_INDEX_SOURCE_PREFIX):
                skipped_indexed += 1
                continue
            # Ya fresco: su último precio es del mismo mes del IPC o posterior.
            if last_date >= ipc_now_date:
                skipped_fresh += 1
                continue

            base = _ipc_on_or_before(ipc, last_date)
            if base is None:
                skipped_nodata += 1  # precio anterior a la serie IPC
                continue
            base_date, base_ipc = base
            ratio = ipc_now / base_ipc
            if ratio <= 1.001:
                skipped_fresh += 1
                continue

            new_price = round(last_price * ratio, 2)
            rows_out.append((m.name, last_date, last_price, ratio, new_price, base_date))
            if not dry:
                record.execute(
                    m.id, new_price,
                    source=f"{_INDEX_SOURCE_PREFIX} INDEC (base {base_date:%Y-%m})",
                    observed_on=ipc_now_date,
                )
            indexed += 1

        if not dry:
            db.commit()

        rows_out.sort(key=lambda r: -r[3])
        print(f"{'material':<34} {'desde':<8} {'precio ant.':>12} {'×':>6} {'→ nuevo':>13}")
        print("-" * 78)
        for name, ld, lp, ratio, np_, _bd in rows_out[:25]:
            print(f"{name[:33]:<34} {ld:%Y-%m}  {lp:>12,.0f} {ratio:>5.2f}x {np_:>13,.0f}")
        if len(rows_out) > 25:
            print(f"  … y {len(rows_out) - 25} más")

        prefix = "[DRY-RUN] " if dry else ""
        print(
            f"\n{prefix}{indexed} materiales indexados a {ipc_now_date:%Y-%m} · "
            f"sin tocar: {skipped_fresh} ya frescos, {skipped_indexed} ya indexados, "
            f"{skipped_nodata} sin precio/histórico."
        )
        if not dry:
            print("Fuente registrada: 'IPC índice INDEC (base AAAA-MM)' — visible en la UI.")
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Actualiza precios por índice IPC (INDEC).")
    p.add_argument("--org", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return run(args.org, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
