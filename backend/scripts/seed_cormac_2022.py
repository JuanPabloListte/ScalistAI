"""Ingesta precios REALES de la lista de Cormac S.A (corralón Córdoba) fechada
**21/01/2022**, transcritos del PDF que aportó el cliente.

Es un **ancla histórica real**: combinada con Carignani (2025) y el scrape de
2448 (2026) construye una serie de precios REAL multi-año por material. El pasado
NO se fabrica — acá se transcribe una fuente observada y fechada.

HONESTO: los precios son los del PDF tal cual (sin ruido, sin deflactar, sin
fallbacks). Cada item se ingesta con observed_on=2022-01-21 + source=Cormac.

Uso:
    python -m scripts.seed_cormac_2022 --dry-run
    python -m scripts.seed_cormac_2022            # ingesta (idempotente: aborta si ya existe)
    python -m scripts.seed_cormac_2022 --force    # re-ingesta aunque ya exista
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

SOURCE = "Cormac S.A (lista 21/01/2022)"
OBSERVED_ON = date(2022, 1, 21)
ORG_ID = 1

# (nombre, precio, unidad, categoria) — transcrito del PDF real de Cormac 21/01/2022
ITEMS: list[tuple[str, float, str, str]] = [
    # --- Áridos ---
    ("Arena fina en bolsa", 80.22, "bolsa", "Áridos"),
    ("Arena fina (m3, de 3 a 7 m3)", 3639.64, "m3", "Áridos"),
    ("Arena gruesa en bolsa", 70.60, "bolsa", "Áridos"),
    ("Arena gruesa (m3, de 3 a 7 m3)", 2090.86, "m3", "Áridos"),
    ("Grancilla 1-3 (m3, de 3 a 7 m3)", 4026.84, "m3", "Áridos"),
    ("Grancilla en bolsa", 80.22, "bolsa", "Áridos"),
    ("Granza 3-5 (m3, de 3 a 7 m3)", 3871.96, "m3", "Áridos"),
    ("Granza material 0-20 (m3, de 3 a 7 m3)", 2787.81, "m3", "Áridos"),
    # --- Cemento y cal ---
    ("Cemento Holcim 50kg", 1044.03, "bolsa", "Cemento y cal"),
    ("Hercal en bolsa 40kg", 716.54, "bolsa", "Cemento y cal"),
    ("Blancaley cal hidratada 25kg", 330.13, "bolsa", "Cemento y cal"),
    ("Blancaley cal viva 25kg", 576.59, "bolsa", "Cemento y cal"),
    # --- Mampostería ---
    ("Ladrillo común x unidad", 33.34, "un", "Mampostería"),
    ("Ladrillón 18x20", 43.54, "un", "Mampostería"),
    ("Bovedilla común x unidad", 36.86, "un", "Mampostería"),
    ("Ladrillo cerámico portante 12x19x33 Palmar", 91.63, "un", "Mampostería"),
    ("Ladrillo cerámico portante 18x19x33 Palmar", 110.82, "un", "Mampostería"),
    ("Ladrillo cerámico tabique 12x18x33 Palmar", 71.43, "un", "Mampostería"),
    ("Ladrillo cerámico tabique 18x18x33 Palmar", 92.20, "un", "Mampostería"),
    ("Ladrillo cerámico tabique 8x18x33 Palmar", 55.79, "un", "Mampostería"),
    ("Ladrillo cerámico techo 11x25x38 Palmar", 130.96, "un", "Mampostería"),
    ("Bloque RU LT-10 p/techo (9x20x40)", 70.13, "un", "Mampostería"),
    ("Bloque RU LT-13 p/techo (12.5x19x39)", 88.87, "un", "Mampostería"),
    ("Bloque RU P-10 (9x19x39)", 66.18, "un", "Mampostería"),
    ("Bloque RU P-13 visto 12.5x19x39", 81.52, "un", "Mampostería"),
    ("Bloque RU P-20 visto 19x19x39", 108.60, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago tabique 8x18x33", 71.97, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago portante 12x18x33", 115.93, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago portante 18x19x33", 137.97, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago tabique 12x18x33", 83.91, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago tabique 18x18x33", 112.16, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago techo 11x25x36", 172.19, "un", "Mampostería"),
    ("Ladrillo cerámica Santiago techo 16x25x36", 229.31, "un", "Mampostería"),
    # --- Hierro y malla ---
    ("Barra hierro 6mm (2.7kg)", 804.53, "un", "Hierro y malla"),
    ("Barra hierro 8mm (4.66kg)", 1088.48, "un", "Hierro y malla"),
    ("Barra hierro 10mm (7.4kg)", 1716.95, "un", "Hierro y malla"),
    ("Barra hierro 12mm (10.64kg)", 2460.30, "un", "Hierro y malla"),
    ("Barra hierro 16mm (18.96kg)", 5769.65, "un", "Hierro y malla"),
    ("Malla 15x25x6mm 2x6m", 7953.67, "un", "Hierro y malla"),
    ("Malla 15x15x5 3x2 F50 mini", 4886.88, "un", "Hierro y malla"),
    ("Malla 15x25x5 3x2 C50 mini", 3909.50, "un", "Hierro y malla"),
    ("Malla 15x15x6mm 2x6m", 21215.84, "un", "Hierro y malla"),
    ("Malla 15x15x8mm 2.15x6m", 37142.83, "un", "Hierro y malla"),
    ("Malla 15x15x4 3x2 PV1", 2576.29, "un", "Hierro y malla"),
    ("Malla 15x25x4 3x2", 2062.08, "un", "Hierro y malla"),
    # --- Viguetas pretensadas ---
    ("Vigueta pretensada 1.00m", 535.76, "un", "Viguetas"),
    ("Vigueta pretensada 1.20m", 644.71, "un", "Viguetas"),
    ("Vigueta pretensada 1.40m", 750.48, "un", "Viguetas"),
    ("Vigueta pretensada 1.60m", 861.47, "un", "Viguetas"),
    ("Vigueta pretensada 1.80m", 963.64, "un", "Viguetas"),
    ("Vigueta pretensada 2.00m", 1072.67, "un", "Viguetas"),
    ("Vigueta pretensada 2.20m", 1183.35, "un", "Viguetas"),
    ("Vigueta pretensada 2.40m", 1289.43, "un", "Viguetas"),
    ("Vigueta pretensada 2.60m", 1395.51, "un", "Viguetas"),
    ("Vigueta pretensada 2.80m", 1499.32, "un", "Viguetas"),
    ("Vigueta pretensada 3.00m", 1608.35, "un", "Viguetas"),
    ("Vigueta pretensada 3.20m", 1657.51, "un", "Viguetas"),
    ("Vigueta pretensada 3.40m", 1795.56, "un", "Viguetas"),
    ("Vigueta pretensada 3.60m", 1846.09, "un", "Viguetas"),
    ("Vigueta pretensada 3.80m", 2128.52, "un", "Viguetas"),
    ("Vigueta pretensada 4.00m", 2219.59, "un", "Viguetas"),
    ("Vigueta pretensada 4.20m", 2330.77, "un", "Viguetas"),
    ("Vigueta pretensada 4.40m", 2718.60, "un", "Viguetas"),
    ("Vigueta pretensada 4.60m", 3212.74, "un", "Viguetas"),
    ("Vigueta pretensada 4.80m", 3574.28, "un", "Viguetas"),
    ("Vigueta pretensada 5.00m", 3967.81, "un", "Viguetas"),
    ("Vigueta pretensada 5.20m", 4141.36, "un", "Viguetas"),
    ("Vigueta pretensada 5.40m", 4896.88, "un", "Viguetas"),
    ("Vigueta pretensada 5.60m", 5074.37, "un", "Viguetas"),
    ("Vigueta pretensada 5.80m", 6622.98, "un", "Viguetas"),
    ("Vigueta pretensada 6.00m", 6856.48, "un", "Viguetas"),
    ("Vigueta pretensada 6.20m", 7081.36, "un", "Viguetas"),
    ("Vigueta pretensada 6.40m", 7638.52, "un", "Viguetas"),
    # --- Revoques, pegamentos, hidrófugo ---
    ("Adhesivo Weber Col Basic 30kg", 714.69, "bolsa", "Revoques y pegamentos"),
    ("Weber Col Pro Nuevo 30kg", 1434.64, "bolsa", "Revoques y pegamentos"),
    ("Weber Ceresita hidrófugo 200kg", 13440.11, "un", "Revoques y pegamentos"),
    ("Weber Ceresita 20kg", 1998.75, "bolsa", "Revoques y pegamentos"),
    ("Weber revoque fino 25kg", 652.30, "bolsa", "Revoques y pegamentos"),
    ("Pastina Weber Prestige porcelanato perla 5kg", 1038.84, "un", "Revoques y pegamentos"),
    ("Pastina Weber Classic plata 5kg", 677.22, "un", "Revoques y pegamentos"),
    ("Weber Rev Promex proyectable interior (2 en 1) 30kg", 722.43, "bolsa", "Revoques y pegamentos"),
    ("Weber Rev Promex proyectable exterior (3 en 1) 30kg", 917.30, "bolsa", "Revoques y pegamentos"),
    ("Weber Mix revoque interior (2 en 1) 30kg", 780.10, "bolsa", "Revoques y pegamentos"),
    # --- Varios obra ---
    ("Fratacho plástico 12x25cm con fieltro", 212.33, "un", "Varios"),
    ("Capa aisladora plástica 0.20x50m", 1401.97, "rollo", "Varios"),
    ("Tubo Awaduct cloacal 110mm x 4.00m", 2176.49, "un", "Plomería"),
]


def run(dry: bool, force: bool) -> None:
    with SessionLocal() as db:
        existing = db.scalar(
            select(func.count(MaterialPriceHistory.id)).where(MaterialPriceHistory.source == SOURCE))
        if existing and not force and not dry:
            print(f"Ya existen {existing} precios con fuente '{SOURCE}'. Usá --force para re-ingestar.")
            return

        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)
        by_name = {m.name: m for m in db.scalars(
            select(Material).where(Material.organization_id == ORG_ID))}
        ingested = 0
        for name, price, unit, category in ITEMS:
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
                record.execute(m.id, price, source=SOURCE, observed_on=OBSERVED_ON)
                ingested += 1
            print(f"  ${price:>11,.2f}  {name[:48]:48} [{category}]{tag}")
        if not dry:
            db.commit()
        prefix = "[DRY-RUN] " if dry else ""
        print(f"\n{prefix}{ingested}/{len(ITEMS)} precios reales ingestados "
              f"(fuente {SOURCE}, fecha {OBSERVED_ON})")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Muestra sin ingestar")
    p.add_argument("--force", action="store_true", help="Re-ingesta aunque ya exista la fuente")
    args = p.parse_args()
    run(args.dry_run, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
