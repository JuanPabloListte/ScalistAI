from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_superadmin
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserUpdate,
    OrganizationCreate,
    OrganizationDetail,
    OrganizationListItem,
    OrganizationRead,
    OrganizationUpdate,
    OrgUserRead,
)

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
) -> User:
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
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=OrgUserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> User:
    user = db.get(User, user_id)
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
    db.commit()
    db.refresh(user)
    return user


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


def _serialize_org(org: Organization) -> OrganizationDetail:
    return OrganizationDetail(
        id=org.id,
        name=org.name,
        subscription_status=org.subscription_status,
        stripe_customer_id=org.stripe_customer_id,
        created_at=org.created_at,
        updated_at=org.updated_at,
        users=[
            OrgUserRead(
                id=u.id,
                email=u.email,
                role=u.org_role,
                is_superadmin=u.is_superadmin,
                created_at=u.created_at,
            )
            for u in sorted(org.users, key=lambda x: x.created_at)
        ],
    )
