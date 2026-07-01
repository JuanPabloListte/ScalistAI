"""Ingesta precios REALES de la comparativa de acopio de Construcciones Silicio
(obra Dúplex, Córdoba) fechada **27/09/2023**, transcrita del PDF del cliente.

Cada ítem trae cotización de 3 proveedores el mismo día (Zárate, Ferrocons,
Cormac) → un Material con varios PricePoint (uno por proveedor). Llena el hueco
temporal 2023 entre Cormac-2022 y Carignani-2025.

HONESTO: precios tal cual del PDF (incluidos outliers reales como la arena fina
o el inodoro de Zárate, notablemente más caros — son la cotización real, no se
corrigen). Sin ruido, sin fallbacks. Filas ambiguas (Tarima, Depósito, Mesadas,
Puerta metálica, ítems sin precio) se omiten.

Uso:
    python -m scripts.seed_acopio_2023 --dry-run
    python -m scripts.seed_acopio_2023            # idempotente: aborta si ya existe
    python -m scripts.seed_acopio_2023 --force
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice
from app.cost_intelligence.infrastructure.persistence.price_repository import SqlPriceHistoryRepository
from app.models.material import Material
from app.models.price_history import MaterialPriceHistory

OBSERVED_ON = date(2023, 9, 27)
ORG_ID = 1
SUPPLIERS = ("Zárate", "Ferrocons", "Cormac")
SOURCE_TPL = "{} (acopio Silicio 27/09/2023)"

# (nombre, unidad, categoría, (precio_Zárate, precio_Ferrocons, precio_Cormac))
# None = sin cotización de ese proveedor. Transcrito del PDF real.
ITEMS: list[tuple[str, str, str, tuple[float | None, float | None, float | None]]] = [
    ("Cemento (bolsa)", "bolsa", "Cemento y cal", (2482.58, 2623.75, 2434.36)),
    ("Hercal (bolsa)", "bolsa", "Cemento y cal", (1921.17, 1693.64, 1748.95)),
    ("Arena gruesa (m3)", "m3", "Áridos", (5817.30, 6210.00, 5728.59)),
    ("Arena fina (m3)", "m3", "Áridos", (38365.45, 10925.00, 10383.06)),
    ("Hidrófugo (kg)", "kg", "Revoques y pegamentos", (460.71, 333.48, 281.62)),
    ("Granza (m3)", "m3", "Áridos", (12376.88, 10925.00, 12517.36)),
    ("Ladrillo de techo (un)", "un", "Mampostería", (None, 313.90, 300.73)),
    ("Pintura asfáltica (tacho)", "tacho", "Pinturas", (15687.90, 13190.08, 14399.84)),
    ("Vigueta 1.5m", "un", "Viguetas", (1470.44, 1576.74, 1946.21)),
    ("Vigueta 3.3m", "un", "Viguetas", (3675.16, 3609.48, 4466.66)),
    ("Vigueta 3.6m", "un", "Viguetas", (3891.35, 3814.34, 4660.26)),
    ("Vigueta 4.6m", "un", "Viguetas", (6291.71, 6401.88, 7217.33)),
    ("Bloque cemento 19x19x39", "un", "Mampostería", (221.71, 232.49, 314.65)),
    ("Ladrillo cerámico 18", "un", "Mampostería", (295.47, 279.18, 267.03)),
    ("Ladrillo cerámico 12", "un", "Mampostería", (245.16, 231.37, 221.03)),
    ("Ladrillo común (un)", "un", "Mampostería", (39.60, 43.86, 41.57)),
    ("Látex exterior (tacho)", "tacho", "Pinturas", (None, None, 16649.73)),
    ("Látex interior (tacho)", "tacho", "Pinturas", (None, None, 18833.76)),
    ("Cerámico blanco (m2)", "m2", "Revestimientos", (2967.09, 1758.11, 2719.18)),
    ("Cerámico gris (m2)", "m2", "Revestimientos", (2240.19, 1757.52, 1557.48)),
    ("Porcelanato gris (m2)", "m2", "Revestimientos", (8849.26, 4429.44, 5557.98)),
    ("Puerta placa 0.70x2.00", "un", "Aberturas", (None, None, 93683.88)),
    ("Puerta placa 0.85x2.20", "un", "Aberturas", (None, None, 125668.79)),
    ("Inodoro (un)", "un", "Sanitarios", (140606.82, 42419.82, 51166.83)),
    ("Bidet (un)", "un", "Sanitarios", (46878.78, 35175.71, 37645.60)),
    ("Bacha baño (un)", "un", "Sanitarios", (None, 32932.57, 43461.96)),
    ("Bacha lavadero (un)", "un", "Sanitarios", (None, 11481.97, 36806.52)),
    ("Bacha cocina (un)", "un", "Sanitarios", (None, 23569.98, 59042.27)),
    ("Bacha antebaño (un)", "un", "Sanitarios", (None, 32932.57, 43461.96)),
    ("Bañadera (un)", "un", "Sanitarios", (None, 109328.81, None)),
    ("Cocina (un)", "un", "Sanitarios", (None, 185984.49, None)),
    ("Flete", "un", "Varios", (None, 6761.83, 7136.39)),
]


def run(dry: bool, force: bool) -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(func.count(MaterialPriceHistory.id)).where(
            MaterialPriceHistory.source.like("%acopio Silicio 27/09/2023%")))
        if existing and not force and not dry:
            print(f"Ya existen {existing} precios de esta fuente. Usá --force para re-ingestar.")
            return

        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)
        by_name = {m.name: m for m in db.scalars(
            select(Material).where(Material.organization_id == ORG_ID))}
        ingested = 0
        for name, unit, category, prices in ITEMS:
            tag = ""
            if not dry:
                m = by_name.get(name)
                if m is None:
                    m = Material(organization_id=ORG_ID, name=name, category=category,
                                 unit=unit, unit_price=0.0)
                    db.add(m)
                    db.flush()
                    by_name[name] = m
                    tag = " [NUEVO]"
            quoted = []
            for supplier, price in zip(SUPPLIERS, prices):
                if price is None:
                    continue
                quoted.append(f"{supplier[:4]}=${price:,.0f}")
                if not dry:
                    record.execute(m.id, price, source=SOURCE_TPL.format(supplier),
                                   observed_on=OBSERVED_ON)
                    ingested += 1
            print(f"  {name[:32]:32} {'  '.join(quoted)}{tag}")
        if not dry:
            db.commit()
        prefix = "[DRY-RUN] " if dry else ""
        print(f"\n{prefix}{ingested} precios reales ingestados "
              f"({len(ITEMS)} materiales, fecha {OBSERVED_ON})")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    run(args.dry_run, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
