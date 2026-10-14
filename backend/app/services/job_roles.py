"""Catálogo y asignación de roles de obra (oficios)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.job_role import DEFAULT_JOB_ROLE_NAMES, JobRole
from app.models.user import User


def ensure_default_job_roles(organization_id: int, db: Session) -> list[JobRole]:
    """Si la org no tiene roles, siembra el catálogo default. Idempotente."""
    existing = list(db.scalars(
        select(JobRole).where(JobRole.organization_id == organization_id)
    ).all())
    if existing:
        return existing

    rows: list[JobRole] = []
    for name in DEFAULT_JOB_ROLE_NAMES:
        row = JobRole(
            organization_id=organization_id,
            name=name,
            is_default=True,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def list_job_roles(organization_id: int, db: Session) -> list[JobRole]:
    ensure_default_job_roles(organization_id, db)
    return list(db.scalars(
        select(JobRole)
        .where(JobRole.organization_id == organization_id)
        .order_by(JobRole.name.asc())
    ).all())


def create_job_role(organization_id: int, name: str, db: Session) -> JobRole:
    ensure_default_job_roles(organization_id, db)
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("El nombre del rol no puede estar vacío")
    if len(cleaned) > 120:
        raise ValueError("El nombre del rol es demasiado largo")
    clash = db.scalar(
        select(JobRole).where(
            JobRole.organization_id == organization_id,
            JobRole.name == cleaned,
        )
    )
    if clash:
        raise ValueError(f"Ya existe el rol «{cleaned}»")
    row = JobRole(organization_id=organization_id, name=cleaned, is_default=False)
    db.add(row)
    db.flush()
    return row


def resolve_job_roles(
    organization_id: int,
    job_role_ids: list[int] | None,
    db: Session,
) -> list[JobRole]:
    """Valida que los ids pertenezcan a la org. None → no cambia (caller decide)."""
    if not job_role_ids:
        return []
    # Dedupe preservando orden: un id repetido violaría la PK de user_job_roles.
    job_role_ids = list(dict.fromkeys(job_role_ids))
    ensure_default_job_roles(organization_id, db)
    rows = list(db.scalars(
        select(JobRole).where(
            JobRole.organization_id == organization_id,
            JobRole.id.in_(job_role_ids),
        )
    ).all())
    found = {r.id for r in rows}
    missing = [i for i in job_role_ids if i not in found]
    if missing:
        raise ValueError(f"Roles inválidos para la organización: {missing}")
    # Preservar orden pedido
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in job_role_ids if i in by_id]


def set_user_job_roles(user: User, roles: list[JobRole]) -> None:
    user.job_roles = list(roles)


def load_user_with_job_roles(user_id: int, db: Session) -> User | None:
    return db.scalars(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.job_roles))
    ).first()
