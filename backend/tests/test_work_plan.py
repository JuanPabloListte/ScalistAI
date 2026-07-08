"""Tests del plan de obra persistido (services/work_plan.py) contra la DB real
del contenedor (los modelos son el corazón del módulo: probarlos con fakes no
verifica nada). Usa un proyecto EFÍMERO con transacción revertida al final —
no deja rastros.

Cubre:
- generate_draft: crea tareas desde el cómputo con dependencias etapa→etapa.
- freeze: draft→active; el active previo pasa a superseded (historial).
- rebaseline: clona a vN+1 con depends_on remapeado a los ids nuevos.
- get_current_plan: draft > active.
- serialize: shape compatible con el Gantt (stages agregadas, totales).
- La inmutabilidad del baseline la valida la API (409), acá la regla de freeze.

Corre directo: python tests/test_work_plan.py (dentro del contenedor backend).
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _setup(db):
    """Proyecto efímero con 1 plan + elementos + receta default, todo en la
    transacción del test."""
    from app.models import Assembly, AssemblyMaterial, DetectedElement, Material, Plan, Project, User
    from sqlalchemy import select

    user = db.scalars(select(User)).first()
    project = Project(organization_id=user.organization_id, user_id=user.id,
                      name="__test_workplan__", status="active", wizard_step=6)
    db.add(project); db.flush()
    plan = Plan(project_id=project.id, original_filename="t.pdf", pdf_path="/tmp/t.pdf",
                dpi=150, page_count=1, status="ready")
    db.add(plan); db.flush()

    mat = Material(organization_id=user.organization_id, name="__test_mat__",
                   category="Test", unit="un", unit_price=100.0)
    db.add(mat); db.flush()
    asm_w = Assembly(organization_id=user.organization_id, name="__test_muro__",
                     applies_to="wall", daily_yield=10.0, stage="Mampostería",
                     stage_order=3, is_default_alternative=True)
    asm_b = Assembly(organization_id=user.organization_id, name="__test_viga__",
                     applies_to="beam", daily_yield=20.0, stage="Estructura",
                     stage_order=2, is_default_alternative=True)
    db.add_all([asm_w, asm_b]); db.flush()
    db.add_all([
        AssemblyMaterial(assembly_id=asm_w.id, material_id=mat.id, consumption=1.0, waste_factor=0.0),
        AssemblyMaterial(assembly_id=asm_b.id, material_id=mat.id, consumption=1.0, waste_factor=0.0),
    ])
    # Elementos SIN assembly asignada → deben tomar la default por tipo.
    db.add_all([
        DetectedElement(plan_id=plan.id, page=1, type="wall", geometry={},
                        length_m=10.0, height_m=2.8, source="dxf", is_candidate=False),
        DetectedElement(plan_id=plan.id, page=1, type="beam", geometry={},
                        length_m=40.0, source="dxf", is_candidate=False),
    ])
    db.flush()
    return project


def test_full_lifecycle():
    from app.core.database import SessionLocal
    from app.services import work_plan as wp

    db = SessionLocal()
    try:
        project = _setup(db)

        # --- draft desde el cómputo: los elementos SIN receta asignada caen a
        # la default del tipo de la org (la que sea) y generan tareas ---
        draft = wp.generate_draft(project.id, db, start_date=dt.date(2026, 8, 1), crews=1)
        s = wp.serialize(draft)
        assert s["status"] == "draft" and s["version"] == 1
        # muro 10m×2.8=28 m² y viga 40 ml deben estar computados en las tareas
        muro = next((t for t in s["tasks"] if t["unit"] == "m²" and abs(t["quantity"] - 28.0) < 0.1), None)
        viga = next((t for t in s["tasks"] if t["unit"] == "ml" and abs(t["quantity"] - 40.0) < 0.1), None)
        assert muro is not None, f"tarea de muro (28 m²) no generada: {[(t['assembly'], t['quantity'], t['unit']) for t in s['tasks']]}"
        assert viga is not None, "tarea de viga (40 ml) no generada"
        assert muro["duration_days"] >= 1 and viga["duration_days"] >= 1
        assert dt.date.fromisoformat(s["start_date"]) == dt.date(2026, 8, 1)
        # dependencia etapa→etapa: la de etapa posterior depende de la previa
        if muro["stage_order"] > viga["stage_order"]:
            assert viga["id"] in muro["depends_on"]
        # etapas agregadas y en orden
        orders = [st["stage_order"] for st in s["stages"]]
        assert orders == sorted(orders)

        # --- regenerar draft: reemplaza, no acumula versiones ---
        draft2 = wp.generate_draft(project.id, db, start_date=dt.date(2026, 8, 1))
        assert draft2.version == 1 or draft2.version == 2  # versión avanza o reusa
        assert wp.get_current_plan(project.id, db).status == "draft"

        # --- freeze: draft→active; freeze de nuevo debe fallar ---
        wp.freeze(draft2, db)
        assert draft2.status == "active" and draft2.frozen_at is not None
        try:
            wp.freeze(draft2, db)
            raise AssertionError("freeze de un plan activo debería fallar")
        except ValueError:
            pass

        # --- rebaseline: clona a draft vN+1 con deps remapeadas ---
        clone = wp.rebaseline(project.id, db)
        assert clone.status == "draft" and clone.version == draft2.version + 1
        s2 = wp.serialize(clone)
        v_active_ids = {t.id for t in draft2.tasks}
        clone_deps = {d for t in s2["tasks"] for d in t["depends_on"]}
        assert not (clone_deps & v_active_ids), "deps del clon apuntan a la versión vieja"
        # el activo sigue activo; el vigente es el draft nuevo
        assert wp.get_current_plan(project.id, db).id == clone.id

        # --- freeze del clon: el activo anterior pasa a superseded ---
        wp.freeze(clone, db)
        db.refresh(draft2)
        assert draft2.status == "superseded" and clone.status == "active"
        versions = wp.list_versions(project.id, db)
        assert [v.status for v in versions] == ["active", "superseded"]

        # --- Etapa 2: avance físico por CANTIDADES ---
        import datetime as _dt

        from app.models.work_plan import ProgressEntry
        from app.services.work_progress import plan_progress

        s3 = wp.serialize(clone)
        muro2 = next(t for t in s3["tasks"] if t["unit"] == "m²" and abs(t["quantity"] - 28.0) < 0.1)
        today = _dt.date(2026, 8, 5)
        # 2 días de trabajo: 8 + 6 = 14 m² de 28 → 50%, rinde 7 m²/día
        db.add(ProgressEntry(task_id=muro2["id"], date=_dt.date(2026, 8, 3), qty_done=8))
        db.add(ProgressEntry(task_id=muro2["id"], date=_dt.date(2026, 8, 4), qty_done=6))
        db.flush()
        db.refresh(clone)
        prog = plan_progress(clone, db, today=today)
        tp = next(t for t in prog["tasks"] if t["task_id"] == muro2["id"])
        assert tp["pct"] == 50.0 and tp["qty_done"] == 14.0
        assert tp["real_yield"] == 7.0 and tp["status"] == "en curso"
        # proyección: faltan 14 m² a 7/día = 2 días desde hoy (ancla max(último, hoy))
        assert tp["projected_end"] == (today + _dt.timedelta(days=2)).isoformat()
        # EV de obra: pct ponderado por costo (el muro pesa lo suyo, no 50% plano)
        totals = prog["totals"]
        assert 0 < totals["pct_fisico"] <= 50.0
        assert abs(totals["ev"] - sum(
            t["cost_planned"] * t["pct"] / 100 for t in prog["tasks"])) < 0.01
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{'1' if not failed else '0'}/1 tests pasaron" if False else f"\n{1 - failed}/1 tests pasaron")
    sys.exit(1 if failed else 0)
