"""Camino crítico (CPM) sobre el grafo de tareas del plan de obra.

Las WorkTask traen `depends_on` (finish-to-start por id, cableado etapa→etapa
al generar el plan). Con eso calculamos, por tarea: inicio/fin temprano (ES/EF)
y tardío (LS/LF), holgura (slack) y si es CRÍTICA (slack 0 → atrasarla atrasa
toda la obra). El grafo es un DAG por construcción; igual el topo-sort es
tolerante a ciclos accidentales (los deja con defaults, no cuelga).

Puro cálculo sobre días-offset desde el inicio; el llamador mapea a fechas.
"""
from __future__ import annotations

from collections import deque


def critical_path(tasks: list[dict]) -> dict:
    """tasks: [{"id", "duration_days", "depends_on": [ids]}]. Devuelve
    {project_duration, tasks: {id: {es,ef,ls,lf,slack,critical}}}."""
    by_id = {t["id"]: t for t in tasks}
    succ: dict[int, list[int]] = {tid: [] for tid in by_id}
    indeg: dict[int, int] = {tid: 0 for tid in by_id}
    for t in tasks:
        for d in (t.get("depends_on") or []):
            if d in by_id:
                succ[d].append(t["id"])
                indeg[t["id"]] += 1

    # Orden topológico (Kahn).
    q = deque([tid for tid, d in indeg.items() if d == 0])
    order: list[int] = []
    indeg_work = dict(indeg)
    while q:
        n = q.popleft()
        order.append(n)
        for s in succ[n]:
            indeg_work[s] -= 1
            if indeg_work[s] == 0:
                q.append(s)
    # Tareas en ciclo (no alcanzadas): se agregan al final con deps ignoradas.
    for tid in by_id:
        if tid not in order:
            order.append(tid)

    dur = {tid: max(0, int(by_id[tid].get("duration_days") or 0)) for tid in by_id}

    # Forward pass: ES/EF.
    es: dict[int, int] = {}
    ef: dict[int, int] = {}
    for tid in order:
        deps = [d for d in (by_id[tid].get("depends_on") or []) if d in ef]
        es[tid] = max((ef[d] for d in deps), default=0)
        ef[tid] = es[tid] + dur[tid]
    project_duration = max(ef.values(), default=0)

    # Backward pass: LF/LS.
    lf: dict[int, int] = {}
    ls: dict[int, int] = {}
    for tid in reversed(order):
        ss = [s for s in succ[tid] if s in ls]
        lf[tid] = min((ls[s] for s in ss), default=project_duration)
        ls[tid] = lf[tid] - dur[tid]

    out = {}
    for tid in by_id:
        slack = ls[tid] - es[tid]
        out[tid] = {
            "es": es[tid], "ef": ef[tid], "ls": ls[tid], "lf": lf[tid],
            "slack": slack, "critical": slack <= 0,
        }
    return {"project_duration": project_duration, "tasks": out}
