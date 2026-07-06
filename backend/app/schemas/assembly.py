from pydantic import BaseModel, ConfigDict, Field

from app.cost_intelligence.domain.measurement import VALID_ENTITY_TYPES
from app.schemas.material import MaterialRead

# Patrón de `applies_to` derivado de la ÚNICA fuente de verdad (measurement).
# Antes estaba hardcodeado y quedó desactualizado al sumar tipos nuevos
# (room_ceiling/pozo/sanitario/boca_electrica): el response_model tiraba 500
# al serializar recetas ya existentes en la DB.
_APPLIES_TO_PATTERN = "^(" + "|".join(VALID_ENTITY_TYPES) + ")$"

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
    applies_to: str = Field(..., pattern=_APPLIES_TO_PATTERN)
    daily_yield: float | None = Field(0.0, description="Rendimiento diario (ej. m2/día)")
    stage: str | None = Field(None, description="Rubro/etapa de obra (ej. Mampostería)")
    stage_order: int | None = Field(0, description="Orden de la etapa en el cronograma")

class AssemblyCreate(AssemblyBase):
    assembly_materials: list[AssemblyMaterialCreate] = []

class AssemblyUpdate(BaseModel):
    name: str | None = None
    applies_to: str | None = None
    daily_yield: float | None = None
    stage: str | None = None
    stage_order: int | None = None
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
