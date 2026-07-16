"""Permisos por proyecto: la matriz de roles y la línea de la plata.

Corre directo: python tests/test_project_access.py (dentro del contenedor).
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _org_with_users(db):
    """Org de test + admin + 3 usuarios sin privilegios."""
    from app.models import Organization, Project, User

    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()

    def _u(role):
        u = User(email=f"__test_{uuid.uuid4().hex[:8]}@t.local", password_hash="x",
                 organization_id=org.id, org_role=role)
        db.add(u); db.flush()
        return u

    admin = _u("admin")
    jefe, capataz, comitente = _u("member"), _u("member"), _u("member")
    project = Project(organization_id=org.id, user_id=admin.id,
                      name="__test_access__", status="active", wizard_step=6)
    db.add(project); db.flush()
    return org, project, admin, jefe, capataz, comitente


def test_sin_miembros_es_retrocompatible():
    """Un proyecto SIN membresías se comporta como antes: cualquiera de la org
    lo ve completo. Es lo que evita romper todo lo existente al desplegar."""
    from app.core.database import SessionLocal
    from app.services.project_access import get_access

    db = SessionLocal()
    try:
        _, project, admin, jefe, _, _ = _org_with_users(db)
        for u in (admin, jefe):
            acc = get_access(project, u, db)
            assert acc.can_view and acc.can_view_financials and acc.can_edit_plan, u.org_role
    finally:
        db.rollback(); db.close()


def test_matriz_de_roles():
    """jefe_obra todo · capataz avanza sin ver plata · comitente solo mira."""
    from app.core.database import SessionLocal
    from app.services import project_access as pa

    db = SessionLocal()
    try:
        _, project, admin, jefe, capataz, comitente = _org_with_users(db)
        pa.set_member(project, jefe.id, "jefe_obra", db)
        pa.set_member(project, capataz.id, "capataz", db)
        pa.set_member(project, comitente.id, "comitente", db)
        db.flush()

        a = pa.get_access(project, jefe, db)
        assert (a.role, a.can_view, a.can_view_financials, a.can_edit_plan,
                a.can_register_progress) == ("jefe_obra", True, True, True, True)

        a = pa.get_access(project, capataz, db)
        assert a.can_view and a.can_register_progress
        assert not a.can_view_financials, "el capataz NO debe ver la plata"
        assert not a.can_edit_plan and not a.can_manage_members

        a = pa.get_access(project, comitente, db)
        assert a.can_view and a.is_client
        assert not a.can_view_financials, "el comitente NO debe ver la plata"
        assert not a.can_register_progress and not a.can_edit_plan

        # El admin de la org no necesita membresía
        a = pa.get_access(project, admin, db)
        assert a.role == "admin" and a.can_view_financials and a.can_manage_members
    finally:
        db.rollback(); db.close()


def test_con_miembros_excluye_a_los_demas():
    """Con el proyecto ya poblado, un miembro de la org que NO fue asignado
    deja de verlo (fin del modo retrocompatible)."""
    from app.core.database import SessionLocal
    from app.services import project_access as pa

    db = SessionLocal()
    try:
        _, project, _, jefe, capataz, _ = _org_with_users(db)
        assert pa.get_access(project, capataz, db).can_view  # antes: sí
        pa.set_member(project, jefe.id, "jefe_obra", db)
        db.flush()
        assert not pa.get_access(project, capataz, db).can_view, (
            "al asignar miembros, los no asignados quedan afuera"
        )
    finally:
        db.rollback(); db.close()


def test_otra_org_no_ve_nada():
    from app.core.database import SessionLocal
    from app.services.project_access import get_access

    db = SessionLocal()
    try:
        _, project, _, _, _, _ = _org_with_users(db)
        _, _, otro_admin, _, _, _ = _org_with_users(db)  # admin de OTRA org
        assert not get_access(project, otro_admin, db).can_view
    finally:
        db.rollback(); db.close()


def test_endpoints_respetan_la_linea_de_la_plata():
    """E2E: el capataz recibe el cronograma SIN importes y 403 en costos."""
    import datetime as dt

    from fastapi.testclient import TestClient

    from app.core.database import SessionLocal
    from app.core.deps import get_current_user
    from app.main import app
    from app.models import Organization, Project
    from app.services import project_access as pa
    from app.services import work_plan as wp
    from tests.test_work_plan import _setup

    db = SessionLocal()
    project = None
    try:
        project = _setup(db)          # trae su propia org + recetas
        org_id = project.organization_id
        from app.models import User
        capataz = User(email=f"__test_{uuid.uuid4().hex[:8]}@t.local",
                       password_hash="x", organization_id=org_id, org_role="member")
        db.add(capataz); db.flush()

        draft = wp.generate_draft(project.id, db, start_date=dt.date(2026, 8, 1))
        wp.freeze(draft, db)
        pa.set_member(project, capataz.id, "capataz", db)
        db.commit()

        app.dependency_overrides[get_current_user] = lambda: capataz
        c = TestClient(app)
        try:
            r = c.get(f"/api/v1/projects/{project.id}/work-plan")
            assert r.status_code == 200
            body = r.json()
            assert body["my_role"] == "capataz"
            assert body["can_view_financials"] is False
            assert body["plan"]["hide_money"] is True
            assert "total_cost" not in body["plan"]
            assert all("cost" not in t for t in body["plan"]["tasks"]), (
                "se filtraron importes al capataz"
            )

            # Costos y presupuesto: prohibidos
            assert c.get(f"/api/v1/projects/{project.id}/work-cost").status_code == 403
            assert c.get(f"/api/v1/projects/{project.id}/actual-costs").status_code == 403
            assert c.get(f"/api/v1/projects/{project.id}/changes").status_code == 403
            # Replanificar: prohibido
            assert c.post(f"/api/v1/projects/{project.id}/work-plan/draft",
                          json={"crews": 1}).status_code == 403
            # Avance: permitido (es su trabajo)
            assert c.get(f"/api/v1/projects/{project.id}/work-progress").status_code == 200
        finally:
            app.dependency_overrides.clear()
    finally:
        if project is not None:
            d2 = SessionLocal()
            p = d2.get(Project, project.id)
            if p is not None:
                org = d2.get(Organization, p.organization_id)
                d2.delete(p)
                d2.commit()
                if org is not None:
                    d2.delete(org); d2.commit()
            d2.close()
        db.rollback(); db.close()


def test_lista_de_proyectos_filtra_por_membresia():
    """El endpoint GET /projects: el admin ve todo; un miembro común ve solo
    los proyectos sin equipo (retrocompat) + donde es miembro."""
    from fastapi.testclient import TestClient

    from app.core.database import SessionLocal
    from app.core.deps import get_current_user
    from app.main import app
    from app.models import Organization, Project, User
    from app.services import project_access as pa

    db = SessionLocal()
    org_id = None
    try:
        org, sin_equipo, admin, jefe, capataz, _ = _org_with_users(db)
        org_id = org.id
        sin_equipo.name = "__test_sin_equipo__"
        con_mio = Project(organization_id=org.id, user_id=admin.id,
                          name="__test_con_mio__", status="active", wizard_step=6)
        con_ajeno = Project(organization_id=org.id, user_id=admin.id,
                            name="__test_ajeno__", status="active", wizard_step=6)
        db.add_all([con_mio, con_ajeno]); db.flush()

        pa.set_member(con_mio, capataz.id, "capataz", db)      # capataz SÍ
        pa.set_member(con_ajeno, jefe.id, "jefe_obra", db)     # capataz NO
        db.commit()

        c = TestClient(app)
        try:
            app.dependency_overrides[get_current_user] = lambda: capataz
            names = {p["name"] for p in c.get("/api/v1/projects").json()}
            assert "__test_con_mio__" in names, "no vio un proyecto donde es miembro"
            assert "__test_sin_equipo__" in names, "no vio un proyecto sin equipo (retrocompat)"
            assert "__test_ajeno__" not in names, "vio un proyecto ajeno con equipo"

            app.dependency_overrides[get_current_user] = lambda: admin
            names_admin = {p["name"] for p in c.get("/api/v1/projects").json()}
            assert "__test_ajeno__" in names_admin, "el admin debe ver todo"
        finally:
            app.dependency_overrides.clear()
    finally:
        # Limpieza total: proyectos (cascade → members), usuarios y la org.
        d2 = SessionLocal()
        if org_id is not None:
            for p in d2.scalars(
                select_projects_of_org(org_id)
            ).all():
                d2.delete(p)
            for u in d2.scalars(select_users_of_org(org_id)).all():
                d2.delete(u)
            org = d2.get(Organization, org_id)
            if org is not None:
                d2.delete(org)
            d2.commit()
        d2.close()
        db.rollback(); db.close()


def select_projects_of_org(org_id):
    from sqlalchemy import select
    from app.models import Project
    return select(Project).where(Project.organization_id == org_id)


def select_users_of_org(org_id):
    from sqlalchemy import select
    from app.models import User
    return select(User).where(User.organization_id == org_id)


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
