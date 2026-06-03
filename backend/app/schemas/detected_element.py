from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.assembly import AssemblyRead


class DetectedElementBase(BaseModel):
    page: int = Field(default=1, ge=1)
    type: str = Field(..., pattern="^(wall|room|opening|beam|roof|column)$")
    geometry: dict = Field(..., description="Coordenadas y geometría en píxeles de la página")
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(2.8, ge=0)
    source: str = Field("manual", pattern="^(manual|ai|ai_ml)$")


class DetectedElementCreate(DetectedElementBase):
    pass


class DetectedElementUpdate(BaseModel):
    geometry: dict | None = None
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(None, ge=0)
    source: str | None = Field(None, pattern="^(manual|ai|ai_ml)$")


class DetectedElementRead(DetectedElementBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    created_at: datetime
    updated_at: datetime
    assemblies: list[AssemblyRead] = []

