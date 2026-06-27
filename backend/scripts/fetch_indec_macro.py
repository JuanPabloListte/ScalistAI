"""Ingesta índices macro REALES de INDEC (datos.gob.ar) a la tabla macro_series.

Indicadores disponibles:
  IPC (vigente):  195.1_NIVEL_GENERAL_0_0_13 — IPC nivel general, nivel de
                  precios, mensual, ACTUAL (termina en el último mes publicado).
  ICC (histórico): 109.3_I1NG_1993_A_22 — ICC GBA Base 1993. OJO: en la API
                  pública está **DISCONTINUADO (termina 2015)**. El ICC actual
                  INDEC solo lo publica en Excel en su web, no por esta API.

Por eso el default es **IPC** (proxy de inflación, real y vigente). Honesto: si
la API de INDEC falla, este script FALLA — NO fabrica datos de fallback.

Uso:
    python -m scripts.fetch_indec_macro                      # IPC (default)
    python -m scripts.fetch_indec_macro --indicator IPC --last 36
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import requests
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.macro_series import MacroSeries

API_URL = "https://apis.datos.gob.ar/series/api/series/"
SOURCE = "INDEC"
SERIES = {
    "IPC": "195.1_NIVEL_GENERAL_0_0_13",
    "ICC": "109.3_I1NG_1993_A_22",  # discontinuado en la API (termina 2015)
}


def fetch(series_id: str, last: int | None) -> list[tuple[str, float]]:
    params = {"ids": series_id, "format": "json"}
    if last:
        params["last"] = last
    resp = requests.get(API_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data")
    if not data:
        raise RuntimeError("La API de INDEC no devolvió datos. NO se fabrica fallback.")
    return [(d, v) for d, v in data if v is not None]


def run(indicator: str, last: int | None) -> None:
    series_id = SERIES[indicator]
    points = fetch(series_id, last)
    with SessionLocal() as db:
        existing = {
            m.date.date().isoformat()
            for m in db.scalars(
                select(MacroSeries).where(MacroSeries.indicator == indicator)
            ).all()
        }
        added = 0
        for date_str, value in points:
            if date_str in existing:
                continue
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            db.add(MacroSeries(indicator=indicator, value=float(value), date=dt, source=SOURCE))
            added += 1
        db.commit()
        total = db.scalar(
            select(func.count(MacroSeries.id)).where(MacroSeries.indicator == indicator)
        )
        print(f"{indicator} INDEC: +{added} puntos nuevos (total {total}). "
              f"Rango API: {points[0][0]} → {points[-1][0]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--indicator", choices=list(SERIES), default="IPC")
    # default a los últimos 120 meses: la API ordena ascendente y pagina de a
    # 100, así que sin --last devolvería el COMIENZO de la serie (1968). Con
    # --last traemos los meses recientes, que es lo que usa el forecaster.
    p.add_argument("--last", type=int, default=120)
    args = p.parse_args()
    run(args.indicator, args.last)
    return 0


if __name__ == "__main__":
    sys.exit(main())
