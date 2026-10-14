from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user, require_org_admin
from app.core.security import hash_password
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate, AdminUserUpdate, JobRoleCreate, JobRoleRead, OrgUserRead,
)
from app.services import job_roles as jr

router = APIRouter(prefix="/team", tags=["team"])


def _org_user_read(user: User, *, include_job_roles: bool = True) -> OrgUserRead:
    return OrgUserRead(
        id=user.id,
        email=user.email,
        role=user.org_role,
        is_superadmin=user.is_superadmin,
        created_at=user.created_at,
        job_roles=(
            [JobRoleRead.model_validate(r) for r in (user.job_roles or [])]
            if include_job_roles
            else []
        ),
    )


@router.get("/users", response_model=list[OrgUserRead])
def list_team(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[OrgUserRead]:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    users = db.scalars(
        select(User)
        .where(User.organization_id == actor.organization_id)
        .options(selectinload(User.job_roles))
        .order_by(User.created_at.asc())
    ).all()
    # Roles de obra: solo visible para admin de la org (o superadmin).
    show_job_roles = bool(actor.is_superadmin or actor.org_role == "admin")
    return [_org_user_read(u, include_job_roles=show_job_roles) for u in users]


@router.get("/job-roles", response_model=list[JobRoleRead])
def list_team_job_roles(
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> list[JobRoleRead]:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    roles = jr.list_job_roles(actor.organization_id, db)
    db.commit()  # persist seed if first time
    return [JobRoleRead.model_validate(r) for r in roles]


@router.post("/job-roles", response_model=JobRoleRead, status_code=status.HTTP_201_CREATED)
def create_team_job_role(
    payload: JobRoleCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> JobRoleRead:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    try:
        role = jr.create_job_role(actor.organization_id, payload.name, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(role)
    return JobRoleRead.model_validate(role)


@router.post("/users", response_model=OrgUserRead, status_code=status.HTTP_201_CREATED)
def create_team_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> OrgUserRead:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        organization_id=actor.organization_id,
        org_role=payload.role,
    )
    db.add(user)
    db.flush()
    try:
        roles = jr.resolve_job_roles(actor.organization_id, payload.job_role_ids, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    jr.set_user_job_roles(user, roles)
    db.commit()
    user = jr.load_user_with_job_roles(user.id, db)
    assert user is not None
    return _org_user_read(user)


@router.patch("/users/{user_id}", response_model=OrgUserRead)
def update_team_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> OrgUserRead:
    user = db.scalars(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.job_roles))
    ).first()
    if user is None or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if payload.email and payload.email != user.email:
        clash = db.scalar(select(User).where(User.email == payload.email, User.id != user.id))
        if clash:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")
        user.email = payload.email
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.role:
        user.org_role = payload.role
    if payload.job_role_ids is not None:
        try:
            roles = jr.resolve_job_roles(actor.organization_id, payload.job_role_ids, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        jr.set_user_job_roles(user, roles)
    db.commit()
    user = jr.load_user_with_job_roles(user_id, db)
    assert user is not None
    return _org_user_read(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> None:
    user = db.get(User, user_id)
    if user is None or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="No podés eliminarte a vos mismo")
    db.delete(user)
    db.commit()
