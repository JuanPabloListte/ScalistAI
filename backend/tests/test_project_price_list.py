"""Lista del proveedor guardada en el proyecto (paso "Precios" del wizard).

Corre directo: python tests/test_project_price_list.py (dentro del contenedor).
Crea una org/proyecto de test con un IFC "listo" sintético y la borra al final.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_price_list_parse import _digimat_like, _zarate_like  # noqa: E402


def _setup(db, ifc_status="ready"):
    from app.models import DetectedElement, Organization, Plan, Project, User

    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()
    user = User(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                organization_id=org.id, org_role="admin")
    db.add(user); db.flush()
    project = Project(organization_id=org.id, user_id=user.id, name="__test_pricelist__",
                      status="draft", wizard_step=2)
    db.add(project); db.flush()
    plan = Plan(project_id=project.id, original_filename="modelo.ifc", pdf_path="/dev/null",
                status=ifc_status)
    db.add(plan); db.flush()
    for t, kw in [("wall", {"length_m": 10, "height_m": 3}),
                  ("column", {"area_m2": 0.04, "height_m": 3}),
                  ("armadura", {"length_m": 120, "geometry": {"kg": 120 * 0.006165 * 64}})]:
        geom = kw.pop("geometry", {})
        db.add(DetectedElement(plan_id=plan.id, page=1, type=t, geometry=geom,
                               source="ifc", **kw))
    db.commit()
    return org, user, project, plan


def _client(user):
    from fastapi.testclient import TestClient

    from app.core.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), lambda: app.dependency_overrides.pop(get_current_user, None)


def _cleanup(db, org_id, project_id=None):
    import shutil

    from app.core.config import settings
    from app.models import Organization

    if project_id is not None:
        shutil.rmtree(Path(settings.STORAGE_DIR) / "price_lists" / str(project_id),
                      ignore_errors=True)
    db.rollback()
    org = db.get(Organization, org_id)
    if org is not None:
        db.delete(org)
        db.commit()
    db.close()


def test_flujo_completo():
    from app.core.database import SessionLocal
    from app.models import Project, ProjectPriceList

    db = SessionLocal()
    org, user, project, _ = _setup(db)
    client, reset = _client(user)
    url = f"/api/v1/projects/{project.id}/price-list"
    try:
        v = client.get(url).json()
        assert v["price_list"] is None and v["model_status"] == "ready"
        assert v["rule_set"]["name"] == "Estándar Argentina"

        r = client.post(url, files={"file": ("digimat.pdf", _digimat_like(), "application/pdf")})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["price_list"]["filename"] == "digimat.pdf"
        assert v["price_list"]["iva"]["included"] is False and v["price_list"]["iva_mode"] == "auto"
        b = v["budget"]
        assert b is not None and b["totals"]["net"] > 0
        cem = next(i for i in b["items"] if i["label"] == "Cemento (mortero de asiento)")
        assert cem["status"] == "ok" and cem["line"]["row"] == 1
        hierro = next(i for i in b["items"] if i["label"] == "Hierro Ø8")
        assert hierro["status"] == "ok"
        db.expire_all()
        p = db.get(Project, project.id)
        assert p.wizard_step == 3 and p.rule_set_id == v["rule_set"]["id"]
        stored = db.query(ProjectPriceList).filter_by(project_id=project.id).one()
        assert Path(stored.file_path).exists()

        # Override: cemento sin precio a propósito.
        v = client.patch(url, json={"overrides": {cem["key"]: None}}).json()
        cem2 = next(i for i in v["budget"]["items"] if i["key"] == cem["key"])
        assert cem2["status"] == "sin_precio" and cem2.get("manual")

        # Corrección de presentación: el cemento pasa a bolsa de 50 kg.
        v = client.patch(url, json={"overrides": {}, "line_patches": {"1": {"amount": 50, "unit": "kg"}}}).json()
        cem3 = next(i for i in v["budget"]["items"] if i["key"] == cem["key"])
        assert cem3["per_sale"] == 50 and v["price_list"]["lines"][0]["patched"]

        # Forzar "con IVA": se re-lee el archivo y el neto baja 21%.
        neto_antes = v["price_list"]["lines"][0]["unit_price_net"]
        v = client.patch(url, json={"iva_mode": "included"}).json()
        assert v["price_list"]["iva_mode"] == "included"
        assert abs(v["price_list"]["lines"][0]["unit_price_net"] - round(neto_antes / 1.21, 2)) < 0.01

        # Reemplazar el archivo borra decisiones y el archivo viejo.
        old_path = stored.file_path
        v = client.post(url, files={"file": ("zarate.pdf", _zarate_like(), "application/pdf")}).json()
        assert v["price_list"]["filename"] == "zarate.pdf"
        assert v["price_list"]["overrides"] == {} and v["price_list"]["line_patches"] == {}
        assert not Path(old_path).exists()

        assert client.post(url, files={"file": ("x.jpg", b"x", "image/jpeg")}).status_code == 400
        assert client.patch(url, json={"rule_set_id": 999999}).status_code == 404

        assert client.delete(url).status_code == 204
        assert client.get(url).json()["price_list"] is None
    finally:
        reset()
        _cleanup(db, org.id, project.id)


def test_modelo_procesandose_guarda_sin_presupuesto():
    from app.core.database import SessionLocal

    db = SessionLocal()
    org, user, project, _ = _setup(db, ifc_status="processing")
    client, reset = _client(user)
    try:
        v = client.post(f"/api/v1/projects/{project.id}/price-list",
                        files={"file": ("d.pdf", _digimat_like(), "application/pdf")}).json()
        assert v["model_status"] == "processing"
        assert v["price_list"] is not None and v["budget"] is None
    finally:
        reset()
        _cleanup(db, org.id, project.id)


def test_otra_org_no_accede():
    from app.core.database import SessionLocal
    from app.models import Organization, User

    db = SessionLocal()
    org, _, project, _ = _setup(db)
    other_org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(other_org); db.flush()
    intruso = User(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                   organization_id=other_org.id, org_role="admin")
    db.add(intruso); db.commit()
    client, reset = _client(intruso)
    try:
        assert client.get(f"/api/v1/projects/{project.id}/price-list").status_code == 404
    finally:
        reset()
        oid = other_org.id
        _cleanup(db, org.id)
        db2 = SessionLocal()
        _cleanup(db2, oid)


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
