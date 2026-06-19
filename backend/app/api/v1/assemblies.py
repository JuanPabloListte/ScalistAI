from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Assembly, AssemblyMaterial, User
from app.schemas.assembly import (
    AssemblyCreate,
    AssemblyUpdate,
    AssemblyRead,
)

router = APIRouter(tags=["assemblies"])

@router.get("/", response_model=list[AssemblyRead])
def list_assemblies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Assembly]:
    stmt = select(Assembly).where(Assembly.organization_id == user.organization_id).order_by(Assembly.name.asc())
    return list(db.scalars(stmt).all())

@router.post("/", response_model=AssemblyRead, status_code=status.HTTP_201_CREATED)
def create_assembly(
    payload: AssemblyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Assembly:
    stmt = select(Assembly).where(
        Assembly.name == payload.name,
        Assembly.organization_id == user.organization_id
    )
    existing = db.scalar(stmt)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un sistema con el nombre '{payload.name}'."
        )

    assembly = Assembly(
        organization_id=user.organization_id,
        name=payload.name,
        applies_to=payload.applies_to,
        daily_yield=payload.daily_yield or 0.0,
        stage=payload.stage,
        stage_order=payload.stage_order or 0,
    )
    db.add(assembly)
    db.flush()

    for am_payload in (payload.materials or []):
        db_am = AssemblyMaterial(
            assembly_id=assembly.id,
            material_id=am_payload.material_id,
            consumption=am_payload.consumption,
            waste_factor=am_payload.waste_factor,
        )
        db.add(db_am)

    db.commit()
    db.refresh(assembly)
    return assembly

@router.get("/{assembly_id}", response_model=AssemblyRead)
def get_assembly(
    assembly_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Assembly:
    assembly = db.get(Assembly, assembly_id)
    if not assembly or assembly.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Sistema no encontrado")
    return assembly

@router.put("/{assembly_id}", response_model=AssemblyRead)
def update_assembly(
    assembly_id: int,
    payload: AssemblyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Assembly:
    assembly = db.get(Assembly, assembly_id)
    if not assembly or assembly.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Sistema no encontrado")

    if payload.name is not None:
        if payload.name != assembly.name:
            stmt = select(Assembly).where(
                Assembly.name == payload.name,
                Assembly.organization_id == user.organization_id
            )
            existing = db.scalar(stmt)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ya existe otro sistema con el nombre '{payload.name}'."
                )
        assembly.name = payload.name

    if payload.applies_to is not None:
        assembly.applies_to = payload.applies_to
        
    if payload.daily_yield is not None:
        assembly.daily_yield = payload.daily_yield

    if payload.stage is not None:
        assembly.stage = payload.stage
    if payload.stage_order is not None:
        assembly.stage_order = payload.stage_order

    if payload.materials is not None:
        for old_am in assembly.assembly_materials:
            db.delete(old_am)
        for am_payload in payload.materials:
            db_am = AssemblyMaterial(
                assembly_id=assembly.id,
                material_id=am_payload.material_id,
                consumption=am_payload.consumption,
                waste_factor=am_payload.waste_factor,
            )
            db.add(db_am)

    db.commit()
    db.refresh(assembly)
    return assembly

@router.delete("/{assembly_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assembly(
    assembly_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assembly = db.get(Assembly, assembly_id)
    if not assembly or assembly.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Sistema no encontrado")
    db.delete(assembly)
    db.commit()
