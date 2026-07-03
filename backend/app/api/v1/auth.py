from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.core.deps import get_current_user
from app.schemas.user import Token, UserRead, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])

# Sin auto-registro público: las cuentas las crea el superadmin (panel admin →
# organizaciones/usuarios) o el admin de cada org (Equipo). El onboarding es
# manual por diseño (el dueño reparte credenciales), así que NO hay endpoint
# /register.


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    user = db.scalar(select(User).where(User.email == form_data.username))
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = create_access_token(subject=user.id)
    return Token(access_token=token)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/profile", response_model=UserRead)
def update_profile(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    if payload.email:
        existing = db.scalar(select(User).where(User.email == payload.email, User.id != user.id))
        if existing:
            raise HTTPException(status_code=400, detail="El email ya está registrado")
        user.email = payload.email
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user

