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

        # --- Etapa 3: costo real + EVM + ajuste por IPC ---
        from app.models.work_plan import ActualCost
        from app.services.work_cost import cost_summary

        ev = totals["ev"]
        # Gasto real = 2× el valor ganado → CPI 0.5, CV negativo (sobrecosto).
        db.add(ActualCost(project_id=project.id, date=today, amount=ev * 2,
                          kind="material", stage="Mampostería"))
        db.flush()
        db.refresh(clone)
        cs = cost_summary(clone, db, today=today)
        e = cs["evm"]
        assert abs(e["ev"] - ev) < 1 and abs(e["ac"] - ev * 2) < 1
        assert abs(e["cpi"] - 0.5) < 0.01           # $1 gastado → $0.5 de avance
        assert e["cv"] < 0                           # sobrecosto
        assert e["eac"] > e["bac"]                   # proyecta terminar sobre presupuesto
        assert cs["by_kind"]["material"] == round(ev * 2, 2)
        # la curva S trae plan y real
        assert any("real" in pt for pt in cs["curve"])
    finally:
        db.rollback()
        db.close()


def test_etapa4_cpm_alerts():
    """CPM + alertas + recalibración de rendimientos sobre un plan congelado.

    - Camino crítico: viga (Estructura) → muro (Mampostería) encadenadas.
    - Retraso que importa: el muro rinde por debajo del plan y se atrasa más
      que su holgura → alerta 'retraso'.
    - Sobrecosto: gasto real >> valor ganado → CPI bajo → alerta 'sobrecosto'.
    - Recalibración: 3+ días de avance con rendimiento real ≠ receta → sugerencia.
    """
    import datetime as _dt

    from app.core.database import SessionLocal
    from app.models.work_plan import ActualCost, ProgressEntry
    from app.services import work_plan as wp
    from app.services.work_alerts import build_alerts

    db = SessionLocal()
    try:
        project = _setup(db)
        draft = wp.generate_draft(project.id, db, start_date=_dt.date(2026, 8, 1), crews=1)
        wp.freeze(draft, db)
        s = wp.serialize(draft)
        muro = next(t for t in s["tasks"] if t["unit"] == "m²" and abs(t["quantity"] - 28.0) < 0.1)
        viga = next(t for t in s["tasks"] if t["unit"] == "ml" and abs(t["quantity"] - 40.0) < 0.1)
        # el muro (etapa posterior) depende de la viga → cadena crítica
        assert viga["id"] in muro["depends_on"]

        # 3 días de avance lento en el muro: 4+4+4 = 12 de 28 → rinde 4/día
        # (plan 10/día) → recalibración -60% y proyección atrasada.
        for d, q in [(3, 4), (4, 4), (5, 4)]:
            db.add(ProgressEntry(task_id=muro["id"], date=_dt.date(2026, 8, d), qty_done=q))
        # gasto real muy por encima del avance → CPI bajo.
        db.add(ActualCost(project_id=project.id, date=_dt.date(2026, 8, 5),
                          amount=5_000_000, kind="material", stage="Mampostería"))
        db.flush()
        db.refresh(draft)

        today = _dt.date(2026, 8, 6)
        r = build_alerts(draft, db, today=today)

        # camino crítico incluye viga y muro
        assert viga["id"] in r["critical_path"] and muro["id"] in r["critical_path"]
        assert r["project_duration"] >= 1

        types = {a["type"] for a in r["alerts"]}
        assert "sobrecosto" in types, f"esperaba alerta de sobrecosto: {types}"
        assert "retraso" in types, f"esperaba alerta de retraso: {types}"

        # recalibración: el muro rinde 4/día, muy por debajo de la receta
        # (la default de la org, sea cual sea su daily_yield) → sugerencia negativa
        ys = next((y for y in r["yield_suggestions"] if abs(y["real_yield"] - 4.0) < 0.1), None)
        assert ys is not None, f"esperaba recalibración del muro: {r['yield_suggestions']}"
        assert ys["planned_yield"] > 0 and ys["diff_pct"] < -50
    finally:
        db.rollback()
        db.close()


def test_jira_workflow_fields():
    """Campos de flujo tipo Jira: estado/prioridad/responsable + historial.

    - FLUJO editable sobre el baseline ACTIVO (no rompe inmutabilidad).
    - BASELINE (duración) sobre activo → PermissionError.
    - Cada cambio queda en el historial de la tarea.
    - Tarea MANUAL: aditiva, arranca al terminar su predecesora (FS).
    """
    import datetime as _dt

    from app.core.database import SessionLocal
    from app.services import work_plan as wp

    db = SessionLocal()
    try:
        project = _setup(db)
        from app.models import User
        from sqlalchemy import select
        org_id = db.get(User, project.user_id).organization_id
        me = project.user_id

        draft = wp.generate_draft(project.id, db, start_date=_dt.date(2026, 8, 1))
        t = draft.tasks[0]
        assert t.status == "pending" and t.priority == "medium" and t.assignees == []

        # flujo sobre borrador (varios responsables, descripción)
        wp.edit_task(t, draft, org_id,
                     {"status": "in_progress", "priority": "high", "assignee_ids": [me],
                      "description": "muro perimetral", "note": "arranca la cuadrilla"}, me, db)
        assert t.status == "in_progress" and t.priority == "high"
        assert [u.id for u in t.assignees] == [me] and t.description == "muro perimetral"
        fields = {e.field for e in t.events}
        assert {"status", "priority", "assignee", "description"} <= fields
        st_ev = next(e for e in t.events if e.field == "status")
        assert st_ev.old_value == "pending" and st_ev.new_value == "in_progress"
        assert st_ev.note == "arranca la cuadrilla"

        # congelar y probar inmutabilidad del baseline vs flujo
        wp.freeze(draft, db)
        try:
            wp.edit_task(t, draft, org_id, {"duration_days": 99}, me, db)
            raise AssertionError("editar duración sobre baseline activo debería fallar")
        except PermissionError:
            pass
        # flujo SÍ se puede sobre el activo
        wp.edit_task(t, draft, org_id, {"status": "in_review"}, me, db)
        assert t.status == "in_review"

        # serialize expone los campos nuevos. expire_all() emula el commit del
        # endpoint (recarga la relación assignees para traer los emails).
        db.expire_all()
        s = wp.serialize(draft)
        st = next(x for x in s["tasks"] if x["id"] == t.id)
        assert st["status"] == "in_review" and st["priority"] == "high"
        assert [a["user_id"] for a in st["assignees"]] == [me]
        assert st["assignees"][0]["email"] and st["description"] == "muro perimetral"

        # desasignar todos con lista vacía
        wp.edit_task(t, draft, org_id, {"assignee_ids": []}, me, db)
        assert t.assignees == []

        # tarea manual (change order) encadenada a t: arranca a t.fin + 1 día
        manual = wp.create_manual_task(
            draft, org_id,
            {"name": "Imprevisto: apuntalar", "stage": "Estructura", "stage_order": 2,
             "duration_days": 3, "depends_on": [t.id], "priority": "critical",
             "assignee_ids": [me]}, me, db)
        assert manual.source == "manual" and manual.status == "pending"
        assert manual.priority == "critical" and [u.id for u in manual.assignees] == [me]
        assert manual.planned_start == t.planned_end + _dt.timedelta(days=1)
        assert manual.planned_end == manual.planned_start + _dt.timedelta(days=3)
        assert any(e.field == "created" for e in manual.events)

        # dependencia inválida (tarea de otro plan / inexistente) → ValueError
        try:
            wp.create_manual_task(draft, org_id,
                                  {"name": "x", "depends_on": [999999]}, me, db)
            raise AssertionError("dependencia inexistente debería fallar")
        except ValueError:
            pass
    finally:
        db.rollback()
        db.close()


def test_work_report_pdf():
    """Reporte ejecutivo PDF end-to-end: arma un plan real con avance + costo y
    genera el PDF, validando que sea un PDF con las secciones esperadas."""
    import datetime as _dt

    import fitz  # PyMuPDF (para leer el PDF generado)

    from app.core.database import SessionLocal
    from app.models.work_plan import ActualCost, ProgressEntry
    from app.services import work_plan as wp
    from app.services.work_alerts import build_alerts
    from app.services.work_cost import cost_summary
    from app.services.work_progress import plan_progress
    from app.services.work_report import build_work_report_pdf, _fmt_compact

    # el compacto entra en una tarjeta y respeta el formato AR
    assert _fmt_compact(-10_980_000) == "-$11,0 M"
    assert _fmt_compact(850_000) == "$850 k"
    assert _fmt_compact(None) == "—"

    db = SessionLocal()
    try:
        project = _setup(db)
        draft = wp.generate_draft(project.id, db, start_date=_dt.date(2026, 8, 1))
        wp.freeze(draft, db)
        s = wp.serialize(draft)
        muro = next(t for t in s["tasks"] if t["unit"] == "m²")
        today = _dt.date(2026, 8, 6)
        for d, q in [(3, 6), (4, 6)]:
            db.add(ProgressEntry(task_id=muro["id"], date=_dt.date(2026, 8, d), qty_done=q))
        db.add(ActualCost(project_id=project.id, date=today, amount=1_000_000,
                          kind="material", stage="Mampostería"))
        db.flush()
        db.refresh(draft)

        pdf = build_work_report_pdf(
            "Proyecto Test", wp.serialize(draft),
            plan_progress(draft, db, today=today),
            cost_summary(draft, db, today=today),
            build_alerts(draft, db, today=today))
        assert pdf[:5] == b"%PDF-" and len(pdf) > 2000

        doc = fitz.open(stream=pdf, filetype="pdf")
        try:
            assert doc.page_count >= 1
            text = "".join(p.get_text() for p in doc)
        finally:
            doc.close()
        for section in ("Reporte de obra", "Proyecto Test", "Estado financiero",
                        "Avance por etapa", "Alertas", "Detalle de tareas"):
            assert section in text, f"falta la sección «{section}» en el PDF"
    finally:
        db.rollback()
        db.close()


def test_comitente_share_link():
    """Link solo-lectura del comitente: crear/rotar/revocar (autenticado) +
    acceso público sin login que sirve el reporte SIN financieros."""
    import datetime as _dt

    import fitz
    from fastapi.testclient import TestClient

    from app.core.database import SessionLocal
    from app.core.deps import get_current_user
    from app.main import app
    from app.models import Project, User
    from app.services import work_plan as wp

    db = SessionLocal()
    try:
        project = _setup(db)
        user = db.get(User, project.user_id)
        draft = wp.generate_draft(project.id, db, start_date=_dt.date(2026, 8, 1))
        wp.freeze(draft, db)
        db.commit()

        app.dependency_overrides[get_current_user] = lambda: user
        c = TestClient(app)
        anon = TestClient(app)  # sin override → simula público, pero el override es global…
        try:
            assert c.get(f"/api/v1/projects/{project.id}/share-link").json()["token"] is None
            tok = c.post(f"/api/v1/projects/{project.id}/share-link").json()["token"]
            assert tok and len(tok) >= 32
            # rotar revoca el anterior
            tok2 = c.post(f"/api/v1/projects/{project.id}/share-link").json()["token"]
            assert tok2 != tok

            # acceso público SIN auth (se limpia el override para el cliente anónimo)
            app.dependency_overrides.clear()
            assert anon.get(f"/api/v1/public/obra/{tok}").status_code == 404  # viejo revocado
            summ = anon.get(f"/api/v1/public/obra/{tok2}")
            assert summ.status_code == 200 and summ.json()["has_report"] is True
            pdf = anon.get(f"/api/v1/public/obra/{tok2}/report.pdf")
            assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
            # el reporte público NO filtra financieros
            text = "".join(p.get_text() for p in fitz.open(stream=pdf.content, filetype="pdf"))
            for leak in ("Estado financiero", "CPI", "Presupuesto", "BAC"):
                assert leak not in text, f"el reporte público filtra «{leak}»"

            # revocar (requiere auth de nuevo) → público deja de resolver
            app.dependency_overrides[get_current_user] = lambda: user
            assert c.delete(f"/api/v1/projects/{project.id}/share-link").status_code == 204
            app.dependency_overrides.clear()
            assert anon.get(f"/api/v1/public/obra/{tok2}").status_code == 404
            assert anon.get("/api/v1/public/obra/inexistente").status_code == 404
        finally:
            app.dependency_overrides.clear()
    finally:
        d2 = SessionLocal()
        d2.delete(d2.get(Project, project.id)); d2.commit(); d2.close()
        db.rollback(); db.close()


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
