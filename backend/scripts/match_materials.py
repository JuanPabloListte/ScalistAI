"""Une materiales equivalentes entre fuentes/fechas bajo un **producto canónico**
(`MaterialGroup`) para consolidar sus precios en UNA serie temporal real.

Filosofía (igual que la detección): el motor **propone**, un humano **aprueba**.
NUNCA se unen productos a ciegas — un match equivocado (distinto color, distinta
marca, distinta medida) envenenaría la serie.

Modos:
    --suggest         (read-only) propone grupos candidatos cross-fuente para revisar
    --apply           crea los grupos CONFIRMED (revisados a mano) y asigna group_id
    --series          imprime la serie temporal consolidada de cada grupo

Los grupos CONFIRMED se definen por IDs exactos (revisados), no por fuzzy: así el
fuzzy solo sirve para DESCUBRIR candidatos, no para decidir.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict, deque

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.material import Material
from app.models.material_group import MaterialGroup
from app.models.price_history import MaterialPriceHistory as MPH

ORG_ID = 1

# Grupos CONFIRMED: (nombre canónico, categoría, unidad, [material_ids]). Revisados
# a mano sobre la salida de --suggest (misma marca / medida / color). Ampliable.
CONFIRMED: list[tuple[str, str, str, list[int]]] = [
    ("Revoque Fino Interior Weber 25kg", "Revoques y pegamentos", "bolsa", [40, 175]),
    ("Pegamento Impermeable Tector 25kg", "Revoques y pegamentos", "bolsa", [42, 48]),
    ("Pegamento Flex Tector 25kg", "Revoques y pegamentos", "bolsa", [43, 47]),
    ("Pastina Weber Classic Plata 5kg", "Revoques y pegamentos", "un", [74, 177]),
    ("Ladrillo común", "Mampostería", "un", [33, 110]),
]

_STOP = {"x", "de", "p", "para", "el", "la", "con", "y", "en", "s", "mm", "kg", "l", "m"}


def _tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("kgs", "kg").replace("mts", "m")
    s = re.sub(r"(\d+)\s*kg", r"\1kg", s)
    s = re.sub(r"(\d+)\s*mm", r"\1mm", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return {t for t in s.split() if t not in _STOP and len(t) > 1}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _material_sources(db) -> dict[int, set[str]]:
    rows = db.execute(
        select(Material.id, MPH.source).join(MPH, MPH.material_id == Material.id)
        .where(Material.organization_id == ORG_ID)).all()
    out: dict[int, set[str]] = defaultdict(set)
    for mid, src in rows:
        out[mid].add(src.split(" (")[0])
    return out


def suggest(threshold: float) -> None:
    with SessionLocal() as db:
        srcs = _material_sources(db)
        mats = {m.id: m for m in db.scalars(
            select(Material).where(Material.organization_id == ORG_ID)) if m.id in srcs}
        toks = {mid: _tokens(m.name) for mid, m in mats.items()}
        ids = [i for i in mats if i not in {x for _, _, _, g in CONFIRMED for x in g}]

        adj: dict[int, set[int]] = defaultdict(set)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if srcs[a] & srcs[b]:          # misma fuente -> no es cross-fuente
                    continue
                if toks[a] and toks[b] and _jaccard(toks[a], toks[b]) >= threshold:
                    adj[a].add(b)
                    adj[b].add(a)

        seen, groups = set(), []
        for start in ids:
            if start in seen or start not in adj:
                continue
            comp, q = [], deque([start])
            seen.add(start)
            while q:
                n = q.popleft()
                comp.append(n)
                for nb in adj[n]:
                    if nb not in seen:
                        seen.add(nb)
                        q.append(nb)
            if len({s for c in comp for s in srcs[c]}) >= 2:
                groups.append(comp)

        print(f"=== {len(groups)} grupos candidatos cross-fuente (Jaccard>={threshold}) — REVISAR ===")
        for g in sorted(groups, key=len, reverse=True):
            print(f"  · grupo de {len(g)}:")
            for mid in g:
                print(f"      id={mid:<4} [{list(srcs[mid])[0][:10]:10}] {mats[mid].name[:46]}")


def apply() -> None:
    with SessionLocal() as db:
        existing = {g.name for g in db.scalars(
            select(MaterialGroup).where(MaterialGroup.organization_id == ORG_ID))}
        created = 0
        for name, category, unit, ids in CONFIRMED:
            if name in existing:
                print(f"  (ya existe) {name}")
                continue
            grp = MaterialGroup(organization_id=ORG_ID, name=name, category=category, unit=unit)
            db.add(grp)
            db.flush()
            members = db.scalars(select(Material).where(Material.id.in_(ids))).all()
            for m in members:
                m.group_id = grp.id
            print(f"  [+] {name}  <- {[m.id for m in members]}")
            created += 1
        db.commit()
        print(f"\n{created} grupos creados ({len(CONFIRMED)} confirmados en total).")


def series() -> None:
    with SessionLocal() as db:
        groups = db.scalars(select(MaterialGroup).where(
            MaterialGroup.organization_id == ORG_ID).order_by(MaterialGroup.name)).all()
        if not groups:
            print("No hay grupos. Corré --apply primero.")
            return
        for g in groups:
            member_ids = [m.id for m in g.members]
            rows = db.execute(
                select(MPH.date, MPH.price, MPH.source)
                .where(MPH.material_id.in_(member_ids)).order_by(MPH.date)).all()
            print(f"\n● {g.name}  ({len(member_ids)} materiales, {len(rows)} puntos)")
            prev = None
            for d, p, s in rows:
                chg = f"  ({(p/prev-1)*100:+.0f}% vs ant.)" if prev else ""
                print(f"    {str(d)[:10]}  ${float(p):>11,.2f}  [{s.split(' (')[0][:12]}]{chg}")
                prev = float(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--series", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.6)
    args = ap.parse_args()
    if args.suggest:
        suggest(args.threshold)
    if args.apply:
        apply()
    if args.series:
        series()
    if not (args.suggest or args.apply or args.series):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
