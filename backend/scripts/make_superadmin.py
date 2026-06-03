"""Marcar un usuario existente como superadmin.

Uso (desde el contenedor backend):
    python -m scripts.make_superadmin user@example.com
"""
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User


def main(email: str) -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No existe usuario con email {email}")
            return 1
        if user.is_superadmin:
            print(f"{email} ya es superadmin")
            return 0
        user.is_superadmin = True
        db.commit()
        print(f"OK: {email} ahora es superadmin")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m scripts.make_superadmin <email>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
