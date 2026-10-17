"""Crea el superadmin del manual en la base DEMO (no hay registro público).

Corre dentro del contenedor backend del manual:
    docker compose -p scalist-manual exec -T backend python - < manual/tools/datos-demo/bootstrap-superadmin.py
Imprime el id del usuario. La contraseña es aleatoria y no se guarda: las capturas
usan un token firmado con el JWT_SECRET del entorno demo. Idempotente.
"""
import secrets

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.user import User

EMAIL = "plataforma@scalist.demo"

with SessionLocal() as db:
    user = db.scalar(select(User).where(User.email == EMAIL))
    if user is None:
        org = db.scalar(select(Organization).where(Organization.name == "Scalist (plataforma)"))
        if org is None:
            org = Organization(name="Scalist (plataforma)", subscription_status="active")
            db.add(org)
            db.flush()
        user = User(email=EMAIL, password_hash=hash_password(secrets.token_urlsafe(24)),
                    organization_id=org.id, org_role="admin", is_superadmin=True)
        db.add(user)
        db.commit()
    print(user.id)
