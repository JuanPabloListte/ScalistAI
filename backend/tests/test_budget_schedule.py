"""Cronograma y plan de obra desde el presupuesto del proyecto (services/budget_schedule).

Corre directo: python tests/test_budget_schedule.py (dentro del contenedor).
Los tests puros no usan DB; el de punta a punta crea una org/proyecto de test
con un IFC "listo" sintético de dos pisos y la borra al final.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _m(**values):
    from app.services.budget_rules import Measures
    return Measures(values=values)


def _view():
    """Presupuesto armado a mano: cemento compartido por muros y columnas
    (un renglón, 3,4 bolsas → se compran 4) + hierro + mano de obra."""
    items = [
        {"key": "1", "measure": "muro_m2", "stage": "Mampostería", "status": "ok",
         "units_to_buy": 2.4},
        {"key": "2", "measure": "columna_m3", "stage": "Estructura", "status": "ok",
         "units_to_buy": 1.0},
        {"key": "3:d8", "measure": "armadura_kg", "stage": "Estructura", "status": "ok",
         "units_to_buy": 10.0},
        {"key": "4", "measure": "techo_m2", "stage": "Cubierta", "status": "sin_precio"},
    ]
    shopping = [
        {"row": 1, "items": ["1", "2"], "units": 3.4, "units_to_buy": 4, "subtotal": 40000.0},
        {"row": 2, "items": ["3:d8"], "units": 10.0, "units_to_buy": 10, "subtotal": 99999.99},
    ]
    labor = [
        {"key": "10", "measure": "muro_m2", "stage": "Mampostería", "days": 12.5, "cost": 100000.0},
        {"key": "11", "measure": "muro_m2", "stage": "Revoques", "days": 5.0, "cost": None},
        {"key": "12", "measure": "columna_m3", "stage": "Estructura", "days": 4.0, "cost": 30000.0},
        {"key": "13", "measure": "techo_m2", "stage": "Cubierta", "days": None, "cost": None},
    ]
    return {"budget": {"items": items, "shopping_list": shopping,
                       "totals": {"net": 139999.99}},
            "labor": {"items": labor, "total": 130000.0}}


def test_reparte_el_redondeo_de_la_lista_de_compras():
    from app.services.budget_schedule import material_costs

    c = material_costs(_view()["budget"])
    # 4 bolsas = $40.000 entre 2,4 (muros) y 1,0 (columnas) unidades.
    assert c["1"] == round(40000 * 2.4 / 3.4, 2) and c["2"] == round(40000 - c["1"], 2), c
    assert round(sum(c.values()), 2) == 139999.99


def test_tareas_por_rubro_medida_y_nivel():
    from app.services.budget_schedule import budget_tasks

    by_level = [("PB", 0, _m(muro_m2=60, columna_m3=2, armadura_kg=300)),
                ("P1", 1, _m(muro_m2=40, columna_m3=2, armadura_kg=100))]
    tasks = budget_tasks(_view(), by_level)
    by = {t["assembly"]: t for t in tasks}
    assert set(by) == {
        "Mampostería (muros) — PB", "Mampostería (muros) — P1",
        "Revoques (muros) — PB", "Revoques (muros) — P1",
        "Estructura (columnas) — PB", "Estructura (columnas) — P1",
        "Estructura (armadura) — PB", "Estructura (armadura) — P1",
    }, sorted(by)  # techo: sin medida en el modelo → no hay tarea
    # La suma del plan = materiales netos + mano de obra.
    assert round(sum(t["cost"] for t in tasks), 2) == round(139999.99 + 130000.0, 2)
    # Muros: 60/40 de la medida → 60/40 del costo y de los días.
    pb, p1 = by["Mampostería (muros) — PB"], by["Mampostería (muros) — P1"]
    assert abs(pb["cost"] / (pb["cost"] + p1["cost"]) - 0.6) < 1e-6
    assert pb["duration_days"] == 8 and p1["duration_days"] == 5  # ceil(7,5) y 5
    assert pb["quantity"] == 60 and pb["unit"] == "m²" and pb["level_order"] == 0
    # Revoques sin precio: tarea con duración y costo 0.
    assert by["Revoques (muros) — PB"]["cost"] == 0 and by["Revoques (muros) — PB"]["duration_days"] == 3
    # Armadura no tiene rendimiento: acompaña a la tarea más larga de su etapa y nivel.
    assert by["Estructura (armadura) — PB"]["duration_days"] == by["Estructura (columnas) — PB"]["duration_days"]
    # El hierro se reparte por kg del piso (300/100).
    assert abs(by["Estructura (armadura) — PB"]["cost"] - 99999.99 * 0.75) < 0.02
    assert by["Mampostería (muros) — PB"]["stage_order"] < by["Revoques (muros) — PB"]["stage_order"]
    assert by["Estructura (columnas) — PB"]["stage_order"] < by["Mampostería (muros) — PB"]["stage_order"]


def test_cuadrillas_y_proyecto_sin_pisos():
    from app.services.budget_schedule import budget_tasks

    tasks = budget_tasks(_view(), [(None, None, _m(muro_m2=100))], crews=2)
    t = next(t for t in tasks if t["assembly"] == "Mampostería (muros)")
    assert t["level"] is None and t["duration_days"] == 7  # ceil(12,5 / 2)


def test_lay_out_estructura_antes_que_mamposteria():
    import datetime as dt

    from app.services.budget_schedule import budget_tasks
    from app.services.schedule import lay_out

    by_level = [("PB", 0, _m(muro_m2=60, columna_m3=2)), ("P1", 1, _m(muro_m2=40, columna_m3=2))]
    s = lay_out(budget_tasks(_view(), by_level), dt.date(2026, 11, 2))
    first = {}
    for t in s["tasks"]:
        first.setdefault(t["stage"], t["start_date"])
    assert first["Estructura"] < first["Mampostería"] < first["Revoques"], first
    assert s["total_cost"] == round(sum(t["cost"] for t in s["tasks"]), 2)


def _setup(db):
    from app.models import DetectedElement, Organization, Plan, Project, User

    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()
    user = User(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                organization_id=org.id, org_role="admin")
    db.add(user); db.flush()
    project = Project(organization_id=org.id, user_id=user.id, name="__test_budget_sched__",
                      status="active", wizard_step=6)
    db.add(project); db.flush()
    plan = Plan(project_id=project.id, original_filename="modelo.ifc", pdf_path="/dev/null",
                status="ready")
    db.add(plan); db.flush()
    for lvl, lo, wall_len in [("PB", 0, 30), ("P1", 1, 10)]:
        for t, kw in [("wall", {"length_m": wall_len, "height_m": 3}),
                      ("column", {"area_m2": 0.04, "height_m": 3}),
                      ("armadura", {"length_m": 120, "geometry": {"kg": 120 * 0.006165 * 64}})]:
            geom = kw.pop("geometry", {})
            db.add(DetectedElement(plan_id=plan.id, page=1, type=t, geometry=geom,
                                   source="ifc", level=lvl, level_order=lo, **kw))
    db.commit()
    return org, user, project


def test_plan_de_obra_alineado_al_presupuesto():
    from test_price_list_parse import _digimat_like
    from test_project_price_list import _cleanup, _client

    from app.core.database import SessionLocal
    from app.models import Project
    from app.services import project_budget as pb
    from app.services import work_plan as wp
    from app.services.schedule import compute_schedule

    db = SessionLocal()
    org, user, project = _setup(db)
    client, reset = _client(user)
    try:
        r = client.post(f"/api/v1/projects/{project.id}/price-list",
                        files={"file": ("digimat.pdf", _digimat_like(), "application/pdf")})
        assert r.status_code == 200, r.text
        # Mano de obra de muros tercerizada a $18.000/m² en esta obra.
        db.expire_all()
        project = db.get(Project, project.id)
        rs = pb.resolve_rule_set(project, db)
        mamp = next(r for r in rs.rules if r.kind == "labor" and r.measure == "muro_m2"
                    and (r.stage or "") == "Mampostería")
        pb.update_budget_settings(project, db, labor={str(mamp.id): {"unit_price": 18000}})
        db.commit()

        price = pb.build_view(project, db)["price"]
        assert price["labor"] > 0 and price["materials"] > 0, price

        # Gantt al vuelo = costo directo del presupuesto.
        s = compute_schedule(project.id, db)
        assert abs(s["total_cost"] - price["direct"]) < 0.02, (s["total_cost"], price)
        names = {t["assembly"] for t in s["tasks"]}
        assert {"Mampostería (muros) — PB", "Mampostería (muros) — P1",
                "Estructura (armadura) — PB"} <= names, names

        # Borrador → congelar: costo del baseline = directo; sin foto de insumos.
        draft = wp.generate_draft(project.id, db)
        plan, _ = wp.freeze(draft, db)
        assert abs(sum(t.cost_planned for t in plan.tasks) - price["direct"]) < 0.02
        assert all(t.assembly_id is None for t in plan.tasks)
        assert wp.serialize(plan)["price_snapshot_count"] == 0

        # Cambios: plan alineado; si el proyecto sube el precio, se ve el delta.
        diff = wp.compute_diff(project.id, db)
        assert diff["n_changed"] == 0, [t for t in diff["tasks"] if t["status"] != "same"]
        pb.update_budget_settings(project, db, labor={str(mamp.id): {"unit_price": 20000}})
        db.commit()
        diff = wp.compute_diff(project.id, db)
        changed = {t["name"] for t in diff["tasks"] if t["status"] == "changed"}
        assert changed == {"Mampostería (muros) — PB", "Mampostería (muros) — P1"}, changed
        assert abs(diff["delta_cost"] - 40 * 3 * 2000) < 0.02  # 120 m² × $2.000

        db.commit()  # suelta el lock de siembra de reglas antes del request
        ch = client.get(f"/api/v1/projects/{project.id}/changes").json()
        direct = pb.build_view(project, db)["price"]["direct"]
        assert ch["summary"]["budget_direct"] == direct, ch["summary"]
        assert abs(ch["summary"]["compute_total"] - direct) < 0.02

        # Re-congelar migra el flujo de tareas por nombre.
        wp.rebaseline(project.id, db)
        nuevo = wp.generate_draft(project.id, db)
        _, mig = wp.freeze(nuevo, db)
        assert mig["migrated_tasks"] == len(nuevo.tasks), mig
    finally:
        reset()
        _cleanup(db, org.id, project.id)


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
            import traceback
            traceback.print_exc()
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
