from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import require_superadmin
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserUpdate,
    JobRoleCreate,
    JobRoleRead,
    OrganizationCreate,
    OrganizationDetail,
    OrganizationListItem,
    OrganizationUpdate,
    OrgUserRead,
)
from app.services import job_roles as jr

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/organizations", response_model=list[OrganizationListItem])
def list_organizations(
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> list[OrganizationListItem]:
    user_counts = dict(
        db.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.organization_id.is_not(None))
            .group_by(User.organization_id)
        ).all()
    )
    project_counts = dict(
        db.execute(
            select(Project.organization_id, func.count(Project.id))
            .where(Project.organization_id.is_not(None))
            .group_by(Project.organization_id)
        ).all()
    )
    orgs = db.scalars(select(Organization).order_by(Organization.created_at.desc())).all()
    return [
        OrganizationListItem(
            id=o.id,
            name=o.name,
            subscription_status=o.subscription_status,
            stripe_customer_id=o.stripe_customer_id,
            created_at=o.created_at,
            updated_at=o.updated_at,
            user_count=user_counts.get(o.id, 0),
            project_count=project_counts.get(o.id, 0),
        )
        for o in orgs
    ]


@router.post("/organizations", response_model=OrganizationDetail, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> OrganizationDetail:
    # Si vienen credenciales de admin, deben venir las dos.
    if (payload.admin_email is None) != (payload.admin_password is None):
        raise HTTPException(status_code=400, detail="Email y password del admin deben venir juntos")

    if payload.admin_email:
        existing = db.scalar(select(User).where(User.email == payload.admin_email))
        if existing:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")

    org = Organization(name=payload.name, subscription_status=payload.subscription_status)
    db.add(org)
    db.flush()

    if payload.admin_email and payload.admin_password:
        admin = User(
            email=payload.admin_email,
            password_hash=hash_password(payload.admin_password),
            organization_id=org.id,
            org_role="admin",
        )
        db.add(admin)

    jr.ensure_default_job_roles(org.id, db)
    db.commit()
    db.refresh(org)
    return _serialize_org(org)


@router.get("/organizations/{org_id}", response_model=OrganizationDetail)
def get_organization(
    org_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> OrganizationDetail:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    return _serialize_org(org)


@router.patch("/organizations/{org_id}", response_model=OrganizationDetail)
def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> OrganizationDetail:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    if payload.name is not None:
        org.name = payload.name
    if payload.subscription_status is not None:
        org.subscription_status = payload.subscription_status
    db.commit()
    db.refresh(org)
    return _serialize_org(org)


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> None:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    db.delete(org)
    db.commit()


@router.post(
    "/organizations/{org_id}/users",
    response_model=OrgUserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user_in_org(
    org_id: int,
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> OrgUserRead:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")

    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        organization_id=org.id,
        org_role=payload.role,
    )
    db.add(user)
    db.flush()
    try:
        roles = jr.resolve_job_roles(org.id, payload.job_role_ids, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    jr.set_user_job_roles(user, roles)
    db.commit()
    user = jr.load_user_with_job_roles(user.id, db)
    assert user is not None
    return _org_user_read(user)


@router.get("/organizations/{org_id}/job-roles", response_model=list[JobRoleRead])
def list_org_job_roles(
    org_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> list[JobRoleRead]:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    roles = jr.list_job_roles(org_id, db)
    db.commit()
    return [JobRoleRead.model_validate(r) for r in roles]


@router.post(
    "/organizations/{org_id}/job-roles",
    response_model=JobRoleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_org_job_role(
    org_id: int,
    payload: JobRoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> JobRoleRead:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    try:
        role = jr.create_job_role(org_id, payload.name, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(role)
    return JobRoleRead.model_validate(role)


@router.patch("/users/{user_id}", response_model=OrgUserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> OrgUserRead:
    user = db.scalars(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.job_roles))
    ).first()
    if user is None:
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
        if user.organization_id is None:
            raise HTTPException(status_code=400, detail="Usuario sin organización")
        try:
            roles = jr.resolve_job_roles(user.organization_id, payload.job_role_ids, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        jr.set_user_job_roles(user, roles)
    db.commit()
    user = jr.load_user_with_job_roles(user_id, db)
    assert user is not None
    return _org_user_read(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_superadmin),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="No podés eliminarte a vos mismo")
    db.delete(user)
    db.commit()


def _org_user_read(user: User) -> OrgUserRead:
    return OrgUserRead(
        id=user.id,
        email=user.email,
        role=user.org_role,
        is_superadmin=user.is_superadmin,
        created_at=user.created_at,
        job_roles=[JobRoleRead.model_validate(r) for r in (user.job_roles or [])],
    )


def _serialize_org(org: Organization) -> OrganizationDetail:
    from sqlalchemy.orm import object_session

    sess = object_session(org)
    if sess is not None:
        users = list(sess.scalars(
            select(User)
            .where(User.organization_id == org.id)
            .options(selectinload(User.job_roles))
            .order_by(User.created_at.asc())
        ).all())
    else:
        users = sorted(org.users, key=lambda x: x.created_at)

    return OrganizationDetail(
        id=org.id,
        name=org.name,
        subscription_status=org.subscription_status,
        stripe_customer_id=org.stripe_customer_id,
        created_at=org.created_at,
        updated_at=org.updated_at,
        users=[_org_user_read(u) for u in users],
    )
