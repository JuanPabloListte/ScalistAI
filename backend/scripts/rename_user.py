"""Renombra el email de un usuario existente (preserva todos sus datos:
proyectos, planos, organización, rol, etc.).

Uso (desde el contenedor backend):
    python -m scripts.rename_user <old_email> <new_email>

Opcionalmente, agregá `--superadmin` para marcarlo como superadmin de paso:
    python -m scripts.rename_user admin@gmail.com juan@gmail.com --superadmin
"""
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User


def main(old_email: str, new_email: str, make_super: bool) -> int:
    if old_email == new_email:
        print("Los emails son iguales, nada para hacer")
        return 0

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == old_email))
        if user is None:
            print(f"ERROR: no existe usuario con email {old_email}")
            return 1

        clash = db.scalar(select(User).where(User.email == new_email))
        if clash is not None:
            print(f"ERROR: ya existe otro usuario con email {new_email} (id={clash.id})")
            print("Si querés fusionar las cuentas, eliminá primero la nueva o renombrala.")
            return 1

        user.email = new_email
        if make_super and not user.is_superadmin:
            user.is_superadmin = True
            print(f"  + marcado como superadmin")

        db.commit()
        db.refresh(user)
        print(f"OK: usuario id={user.id} ahora es {user.email} "
              f"(rol={user.org_role}, superadmin={user.is_superadmin}, org={user.organization_id})")
        return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    make_super = "--superadmin" in args
    args = [a for a in args if a != "--superadmin"]
    if len(args) != 2:
        print("Uso: python -m scripts.rename_user <old_email> <new_email> [--superadmin]")
        sys.exit(2)
    sys.exit(main(args[0], args[1], make_super))
