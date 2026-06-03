from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_org_admin
from app.core.security import hash_password
from app.models.user import User
from app.schemas.admin import AdminUserCreate, AdminUserUpdate, OrgUserRead

router = APIRouter(prefix="/team", tags=["team"])


@router.get("/users", response_model=list[OrgUserRead])
def list_team(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[User]:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    users = db.scalars(
        select(User)
        .where(User.organization_id == actor.organization_id)
        .order_by(User.created_at.asc())
    ).all()
    return users


@router.post("/users", response_model=OrgUserRead, status_code=status.HTTP_201_CREATED)
def create_team_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> User:
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
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=OrgUserRead)
def update_team_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> User:
    user = db.get(User, user_id)
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
    db.commit()
    db.refresh(user)
    return user


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
