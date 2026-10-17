"""Permisos por HTTP sobre planos y catálogos de la org.

- Planos: usan project_access (no alcanza con ser de la org: si el proyecto
  tiene equipo, rige la membresía; el comitente mira pero no edita).
- Catálogos de la org (materiales, sistemas, gastos generales, rubros
  paramétricos): leer cualquiera, escribir solo el admin de la org.

Corre directo: python tests/test_plan_permissions.py (dentro del contenedor).
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_project_access import (  # noqa: E402
    _org_with_users, select_projects_of_org, select_users_of_org,
)


def _cleanup(*org_ids):
    from app.core.database import SessionLocal
    from app.models import Organization

    d2 = SessionLocal()
    try:
        for org_id in org_ids:
            if org_id is None:
                continue
            for p in d2.scalars(select_projects_of_org(org_id)).all():
                d2.delete(p)
            for u in d2.scalars(select_users_of_org(org_id)).all():
                d2.delete(u)
            org = d2.get(Organization, org_id)
            if org is not None:
                d2.delete(org)
        d2.commit()
    finally:
        d2.close()


def _client_as(user):
    from fastapi.testclient import TestClient

    from app.core.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_planos_respetan_membresia_y_rol():
    from app.core.database import SessionLocal
    from app.main import app
    from app.models import Plan
    from app.services import project_access as pa

    db = SessionLocal()
    org_ids = []
    try:
        org, project, _, jefe, _, comitente = _org_with_users(db)
        org_ids.append(org.id)
        otra_org, _, ajeno, _, _, _ = _org_with_users(db)
        org_ids.append(otra_org.id)
        plan = Plan(project_id=project.id, original_filename="x.pdf",
                    pdf_path="/nonexistent/x.pdf", page_count=1)
        db.add(plan); db.flush()
        pa.set_member(project, jefe.id, "jefe_obra", db)
        pa.set_member(project, comitente.id, "comitente", db)
        db.commit()
        pid = plan.id
        escala = {"page": 1, "denominator": 100}

        try:
            # Otra org: no ve el plano (404, no filtramos existencia).
            c = _client_as(ajeno)
            assert c.get(f"/api/v1/plans/{pid}/elements").status_code == 404
            assert c.post(f"/api/v1/plans/{pid}/scale-ratio", json=escala).status_code == 404
            assert c.get(f"/api/v1/plans/{pid}/dxf-info").status_code == 404

            # Comitente: mira, no edita.
            c = _client_as(comitente)
            assert c.get(f"/api/v1/plans/{pid}/elements").status_code == 200
            assert c.get(f"/api/v1/plans/{pid}/render-status").status_code == 200
            assert c.post(f"/api/v1/plans/{pid}/scale-ratio", json=escala).status_code == 403
            assert c.patch(f"/api/v1/plans/{pid}/page-roles",
                           json={"page_roles": {}}).status_code == 403
            assert c.post(f"/api/v1/plans/{pid}/dxf-layers/apply",
                          json={"mapping": {}}).status_code == 403
            assert c.post(f"/api/v1/plans/{pid}/elements/bulk/delete",
                          json=[]).status_code == 403

            # Jefe de obra: edita.
            c = _client_as(jefe)
            r = c.post(f"/api/v1/plans/{pid}/scale-ratio", json=escala)
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()
    finally:
        db.rollback(); db.close()
        _cleanup(*org_ids)


def test_catalogos_de_la_org_solo_admin_escribe():
    from app.core.database import SessionLocal
    from app.main import app

    db = SessionLocal()
    org_id = None
    try:
        org, _, admin, miembro, _, _ = _org_with_users(db)
        org_id = org.id
        db.commit()
        material = {"name": f"__test_mat_{uuid.uuid4().hex[:6]}",
                    "category": "Test", "unit": "un"}

        try:
            c = _client_as(miembro)
            # Leer: cualquiera de la org.
            assert c.get("/api/v1/materials/").status_code == 200
            assert c.get("/api/v1/cost-settings").status_code == 200
            # Escribir: no.
            assert c.post("/api/v1/materials/", json=material).status_code == 403
            assert c.put("/api/v1/materials/999999", json=material).status_code == 403
            assert c.delete("/api/v1/materials/999999").status_code == 403
            assert c.post("/api/v1/materials/import-json", json=[]).status_code == 403
            assert c.delete("/api/v1/assemblies/999999").status_code == 403
            assert c.put("/api/v1/cost-settings",
                         json={"overhead_pct": 99}).status_code == 403
            assert c.put("/api/v1/parametric-rubros",
                         json={"rubros": []}).status_code == 403

            c = _client_as(admin)
            r = c.post("/api/v1/materials/", json=material)
            assert r.status_code == 201, r.text
        finally:
            app.dependency_overrides.clear()
    finally:
        db.rollback(); db.close()
        _cleanup(org_id)


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
