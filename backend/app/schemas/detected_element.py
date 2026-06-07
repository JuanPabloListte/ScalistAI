from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assembly import AssemblyRead


class ElementSource(str, Enum):
    manual = "manual"    # dibujado a mano por el usuario en el editor
    ai = "ai"            # sugerido por IA y aceptado explícitamente por el usuario
    ai_ml = "ai_ml"      # detectado automáticamente por el pipeline ML en background
    dxf = "dxf"          # importado desde capas de un archivo DXF


class DetectedElementBase(BaseModel):
    page: int = Field(default=1, ge=1)
    type: str = Field(..., pattern="^(wall|room|opening|beam|roof|column|riostra|cloaca|electricidad)$")
    geometry: dict = Field(..., description="Coordenadas y geometría en píxeles de la página")
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(2.8, ge=0)
    source: ElementSource = ElementSource.manual


class DetectedElementCreate(DetectedElementBase):
    pass


class DetectedElementUpdate(BaseModel):
    geometry: dict | None = None
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(None, ge=0)
    source: ElementSource | None = None


class DetectedElementRead(DetectedElementBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    created_at: datetime
    updated_at: datetime
    assemblies: list[AssemblyRead] = []

