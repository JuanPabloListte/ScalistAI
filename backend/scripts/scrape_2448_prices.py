"""Scrapea precios REALES del catálogo de 2448 Materiales (Tiendanube) e ingesta
a `material_price_history`.

Parsea los **datos estructurados JSON-LD** (schema.org `Product`/`Offer`) que la
tienda embebe en el HTML → robusto, no depende de clases CSS frágiles. Cada
corrida es un snapshot: el precio queda con fecha + `source="2448materiales.com.ar"`.

HONESTO: si la página falla o no devuelve productos, este script **FALLA y
avisa** — NUNCA inventa precios de fallback.

Uso:
    python -m scripts.scrape_2448_prices --query "cemento holcim" --dry-run
    python -m scripts.scrape_2448_prices            # set de queries por defecto, ingesta
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

import requests
from sqlalchemy import select

from app.core.database import SessionLocal
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice
from app.cost_intelligence.infrastructure.persistence.price_repository import SqlPriceHistoryRepository
from app.models.material import Material

BASE_URL = "https://2448materiales.com.ar/search/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
SOURCE = "2448materiales.com.ar"
ORG_ID = 1
DEFAULT_QUERIES = ["cemento holcim", "revoque weber", "hidrofugo ceresita", "pegamento porcelanato"]

_LDJSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
_CODE_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")  # quita el código tipo " (80)" al final


def _products_from_html(html: str) -> list[tuple[str, float]]:
    """Extrae (nombre, precio) de los bloques JSON-LD de tipo Product."""
    out: list[tuple[str, float]] = []
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            objs = data
        elif isinstance(data, dict):
            objs = data.get("@graph", [data])
        else:
            continue
        for obj in objs:
            if not isinstance(obj, dict) or obj.get("@type") != "Product":
                continue
            name = obj.get("name")
            offers = obj.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price") if isinstance(offers, dict) else None
            if not name or price is None:
                continue
            try:
                out.append((_CODE_SUFFIX_RE.sub("", name.strip()), float(price)))
            except (TypeError, ValueError):
                continue
    return out


def fetch(query: str) -> list[tuple[str, float]]:
    resp = requests.get(BASE_URL, params={"q": query}, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    products = _products_from_html(resp.text)
    if not products:
        raise RuntimeError(f"'{query}': la página no devolvió productos JSON-LD. NO se inventa nada.")
    return products


def run(queries: list[str], dry: bool) -> None:
    with SessionLocal() as db:
        repo = SqlPriceHistoryRepository(db)
        record = RecordMaterialPrice(repo)
        by_name = {m.name: m for m in db.scalars(
            select(Material).where(Material.organization_id == ORG_ID))}
        ingested = 0
        for query in queries:
            products = fetch(query)
            print(f"=== '{query}': {len(products)} productos ===")
            for name, price in products:
                tag = ""
                if not dry:
                    m = by_name.get(name)
                    if m is None:
                        m = Material(organization_id=ORG_ID, name=name,
                                     category="Materiales (web 2448)", unit="un", unit_price=0.0)
                        db.add(m)
                        db.flush()
                        by_name[name] = m
                        tag = " [NUEVO]"
                    record.execute(m.id, price, source=SOURCE, observed_on=date.today())
                    ingested += 1
                print(f"  ${price:>11,.2f}  {name[:52]}{tag}")
        if not dry:
            db.commit()
        prefix = "[DRY-RUN] " if dry else ""
        print(f"\n{prefix}{ingested} precios reales ingestados "
              f"(fuente {SOURCE}, fecha {date.today()})")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--query", action="append", help="Búsqueda (repetible). Default: set estándar.")
    p.add_argument("--dry-run", action="store_true", help="Muestra sin ingestar")
    args = p.parse_args()
    run(args.query or DEFAULT_QUERIES, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
