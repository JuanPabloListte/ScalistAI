from pydantic import BaseModel, ConfigDict, Field
from app.schemas.material import MaterialRead

class AssemblyMaterialBase(BaseModel):
    material_id: int
    consumption: float = Field(..., ge=0)
    waste_factor: float = Field(0.0, ge=0)

class AssemblyMaterialCreate(AssemblyMaterialBase):
    pass

class AssemblyMaterialRead(AssemblyMaterialBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    assembly_id: int
    material: MaterialRead

class AssemblyBase(BaseModel):
    name: str
    applies_to: str = Field(..., pattern="^(wall|room_floor|room_wall|room_perimeter|opening|opening_perimeter|beam|roof|column|riostra|cloaca|electricidad|escalera)$")
    daily_yield: float | None = Field(0.0, description="Rendimiento diario (ej. m2/día)")

class AssemblyCreate(AssemblyBase):
    assembly_materials: list[AssemblyMaterialCreate] = []

class AssemblyUpdate(BaseModel):
    name: str | None = None
    applies_to: str | None = None
    daily_yield: float | None = None
    assembly_materials: list[AssemblyMaterialCreate] | None = None

class AssemblyRead(AssemblyBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    assembly_materials: list[AssemblyMaterialRead] = []

class AssemblyAssignRequest(BaseModel):
    assembly_id: int

class AssemblyBulkAssignRequest(BaseModel):
    element_ids: list[int] = Field(..., min_items=1)
    assembly_id: int

class AssemblyBulkRemoveRequest(BaseModel):
    element_ids: list[int] = Field(..., min_items=1)
    assembly_id: int
