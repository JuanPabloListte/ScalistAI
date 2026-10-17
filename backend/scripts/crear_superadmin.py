"""Crea el primer superadmin en una instalación nueva (no hay registro público).

Uso (en el servidor):
    docker compose -f docker-compose.prod.yml exec backend python -m scripts.crear_superadmin vos@tuempresa.com
Pide la contraseña por teclado (no queda en el historial). Si el usuario ya
existe, solo lo marca como superadmin.

También acomoda el contador de ids de organizaciones: la migración inicial
inserta la organización 1 a mano y, sin esto, la primera organización que se
crea desde la app falla con error 500.
"""
import getpass
import sys

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.user import User


def main(email: str) -> int:
    with SessionLocal() as db:
        db.execute(text(
            "SELECT setval('organizations_id_seq', GREATEST((SELECT MAX(id) FROM organizations), 1))"
        ))
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.is_superadmin = True
            db.commit()
            print(f"OK: {email} ya existía; ahora es superadmin")
            return 0

        password = getpass.getpass("Contraseña (mínimo 8 caracteres): ")
        if len(password) < 8 or password != getpass.getpass("Repetila: "):
            print("Las contraseñas no coinciden o tienen menos de 8 caracteres.")
            return 1

        org = db.scalar(select(Organization).order_by(Organization.id))
        if org is None:
            org = Organization(name="Scalist", subscription_status="active")
            db.add(org)
            db.flush()
        db.add(User(email=email, password_hash=hash_password(password),
                    organization_id=org.id, org_role="admin", is_superadmin=True))
        db.commit()
        print(f"OK: superadmin {email} creado en la organización «{org.name}»")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m scripts.crear_superadmin <email>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
