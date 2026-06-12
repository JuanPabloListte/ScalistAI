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
    type: str = Field(..., pattern="^(wall|room|opening|beam|roof|column|riostra|cloaca|electricidad|escalera)$")
    geometry: dict = Field(..., description="Coordenadas y geometría en píxeles de la página")
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(2.8, ge=0)
    source: ElementSource = ElementSource.manual
    is_candidate: bool = Field(
        default=False,
        description="Propuesta de la IA pendiente de aprobación; no computa hasta aceptarse",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class DetectedElementCreate(DetectedElementBase):
    pass


class DetectedElementUpdate(BaseModel):
    geometry: dict | None = None
    length_m: float | None = Field(None, ge=0)
    area_m2: float | None = Field(None, ge=0)
    height_m: float | None = Field(None, ge=0)
    source: ElementSource | None = None
    is_candidate: bool | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class CandidateBulkAction(BaseModel):
    """Aceptar o descartar propuestas de la IA (is_candidate=True) en lote.

    `element_ids=None` aplica a todos los candidatos del plan (opcionalmente
    filtrados por página).
    """

    action: str = Field(..., pattern="^(accept|discard)$")
    element_ids: list[int] | None = None
    page: int | None = Field(None, ge=1)


class DetectedElementRead(DetectedElementBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    created_at: datetime
    updated_at: datetime
    assemblies: list[AssemblyRead] = []

