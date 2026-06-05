from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
import io
import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Material, User
from app.schemas.material import (
    MaterialCreate,
    MaterialUpdate,
    MaterialRead,
)

router = APIRouter(tags=["materials"])

@router.get("/", response_model=list[MaterialRead])
def list_materials(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Material]:
    stmt = select(Material).where(Material.organization_id == user.organization_id).order_by(Material.name.asc())
    return list(db.scalars(stmt).all())

@router.post("/", response_model=MaterialRead, status_code=status.HTTP_201_CREATED)
def create_material(
    payload: MaterialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    stmt = select(Material).where(
        Material.name == payload.name,
        Material.organization_id == user.organization_id
    )
    existing = db.scalar(stmt)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un material con el nombre '{payload.name}'."
        )

    material = Material(
        organization_id=user.organization_id,
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        unit_price=payload.unit_price,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material

@router.get("/{material_id}", response_model=MaterialRead)
def get_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    material = db.get(Material, material_id)
    if not material or material.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    return material

@router.put("/{material_id}", response_model=MaterialRead)
def update_material(
    material_id: int,
    payload: MaterialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    material = db.get(Material, material_id)
    if not material or material.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    if payload.name is not None:
        if payload.name != material.name:
            stmt = select(Material).where(
                Material.name == payload.name,
                Material.organization_id == user.organization_id
            )
            existing = db.scalar(stmt)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ya existe otro material con el nombre '{payload.name}'."
                )
        material.name = payload.name

    if payload.category is not None:
        material.category = payload.category
    if payload.unit is not None:
        material.unit = payload.unit
    if payload.unit_price is not None:
        material.unit_price = payload.unit_price

    db.commit()
    db.refresh(material)
    return material

@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    material = db.get(Material, material_id)
    if not material or material.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    db.delete(material)
    db.commit()

from pydantic import BaseModel

class MaterialImportItem(BaseModel):
    name: str
    category: str = "General"
    unit: str = "un"
    unit_price: float = 0.0

@router.post("/import-json", response_model=dict)
def import_materials_json(
    items: list[MaterialImportItem],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    imported_count = 0
    updated_count = 0
    
    if not items:
        return {"imported": 0, "updated": 0}
        
    # Pre-cargar todos los materiales existentes de la organización
    stmt = select(Material).where(Material.organization_id == user.organization_id)
    existing_materials = {m.name: m for m in db.scalars(stmt).all()}
    
    for item in items:
        name = item.name.strip()
        if not name:
            continue
            
        category = item.category.strip() if item.category else "General"
        unit = item.unit.strip() if item.unit else "un"
        unit_price = item.unit_price if item.unit_price is not None else 0.0
            
        if name in existing_materials:
            # Upsert
            mat = existing_materials[name]
            mat.category = category
            mat.unit = unit
            mat.unit_price = unit_price
            updated_count += 1
        else:
            # Crear
            mat = Material(
                organization_id=user.organization_id,
                name=name,
                category=category,
                unit=unit,
                unit_price=unit_price
            )
            db.add(mat)
            existing_materials[name] = mat # Por si hay duplicados en la misma peticion
            imported_count += 1
            
    db.commit()
    
    return {"imported": imported_count, "updated": updated_count}


