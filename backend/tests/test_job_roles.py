"""Roles de obra (oficios): catálogo por org, asignación y aislamiento.

Corre directo: python tests/test_job_roles.py (dentro del contenedor).
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _org_with_user(db):
    from app.models import Organization, User

    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()
    user = User(email=f"__test_{uuid.uuid4().hex[:8]}@t.local", password_hash="x",
                organization_id=org.id, org_role="member")
    db.add(user); db.flush()
    return org, user


def test_seed_default_idempotente():
    from app.core.database import SessionLocal
    from app.models.job_role import DEFAULT_JOB_ROLE_NAMES
    from app.services import job_roles as jr

    db = SessionLocal()
    try:
        org, _ = _org_with_user(db)
        first = jr.list_job_roles(org.id, db)
        second = jr.list_job_roles(org.id, db)
        assert len(first) == len(DEFAULT_JOB_ROLE_NAMES)
        assert len(second) == len(first), "el seed no debe duplicarse"
        assert all(r.is_default for r in first)
    finally:
        db.rollback(); db.close()


def test_crear_rol_normaliza_y_rechaza_duplicado():
    from app.core.database import SessionLocal
    from app.services import job_roles as jr

    db = SessionLocal()
    try:
        org, _ = _org_with_user(db)
        role = jr.create_job_role(org.id, "  Impermeabilizador   de terrazas ", db)
        assert role.name == "Impermeabilizador de terrazas"
        assert role.is_default is False
        try:
            jr.create_job_role(org.id, "Impermeabilizador de terrazas", db)
            raise AssertionError("debería rechazar el duplicado")
        except ValueError:
            pass
    finally:
        db.rollback(); db.close()


def test_asignar_roles_dedupe_y_reemplazo():
    from app.core.database import SessionLocal
    from app.services import job_roles as jr

    db = SessionLocal()
    try:
        org, user = _org_with_user(db)
        roles = jr.list_job_roles(org.id, db)
        a, b = roles[0].id, roles[1].id

        jr.set_user_job_roles(user, jr.resolve_job_roles(org.id, [a, b, a], db))
        db.flush()
        loaded = jr.load_user_with_job_roles(user.id, db)
        assert sorted(r.id for r in loaded.job_roles) == sorted([a, b])

        jr.set_user_job_roles(user, jr.resolve_job_roles(org.id, [], db))
        db.flush()
        assert jr.load_user_with_job_roles(user.id, db).job_roles == []
    finally:
        db.rollback(); db.close()


def test_rol_de_otra_org_es_invalido():
    from app.core.database import SessionLocal
    from app.services import job_roles as jr

    db = SessionLocal()
    try:
        org_a, _ = _org_with_user(db)
        org_b, _ = _org_with_user(db)
        ajeno = jr.list_job_roles(org_b.id, db)[0].id
        try:
            jr.resolve_job_roles(org_a.id, [ajeno], db)
            raise AssertionError("no debe aceptar roles de otra organización")
        except ValueError:
            pass
    finally:
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
