from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BuildingType = Literal["casa", "edificio", "condominio", "comercial"]

# Claves obligatorias en building_info por tipo. Si el frontend manda
# un set distinto, el endpoint /building-info devuelve 422.
BUILDING_FIELDS: dict[str, set[str]] = {
    "casa": {"area_cubierta_m2", "area_descubierta_m2", "pisos", "habitaciones", "banos"},
    "edificio": {"area_total_m2", "pisos", "unidades_por_piso", "area_unidad_m2"},
    "condominio": {"area_comun_m2", "area_privada_m2", "num_unidades", "pisos"},
    "comercial": {"area_cubierta_m2", "area_descubierta_m2", "pisos", "num_locales"},
}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class LocationUpdate(BaseModel):
    address: str = Field(min_length=1, max_length=512)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    city: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, max_length=128)


class BuildingInfoUpdate(BaseModel):
    building_type: BuildingType
    building_info: dict[str, float]

    @field_validator("building_info")
    @classmethod
    def _validate_fields(cls, value: dict[str, float], info) -> dict[str, float]:  # noqa: ANN001
        b_type = info.data.get("building_type")
        if not b_type:
            return value
        required = BUILDING_FIELDS[b_type]
        missing = required - value.keys()
        if missing:
            raise ValueError(f"Faltan campos para tipo '{b_type}': {sorted(missing)}")
        extra = value.keys() - required
        if extra:
            raise ValueError(f"Campos no permitidos para tipo '{b_type}': {sorted(extra)}")
        for key, val in value.items():
            if val < 0:
                raise ValueError(f"'{key}' debe ser mayor o igual a 0")
        return value


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: str
    wizard_step: int

    address: str | None
    latitude: float | None
    longitude: float | None
    city: str | None
    country: str | None

    building_type: str | None
    building_info: dict[str, Any] | None

    allow_training_data: bool = True

    created_at: datetime


class TrainingConsentUpdate(BaseModel):
    """Toggle del consentimiento de uso de datos del proyecto para training."""

    allow_training_data: bool
