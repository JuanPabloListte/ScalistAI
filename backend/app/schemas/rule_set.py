from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.budget_rules import MEASURES, MODES, UNITS


class RuleIn(BaseModel):
    measure: str
    label: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(min_length=1)
    exclude_keywords: list[str] = Field(default_factory=list)
    unit: str
    factor: float = Field(ge=0)
    mode: str = "fixed"
    waste_pct: float = Field(default=0, ge=0, le=100)
    notes: str | None = None

    @field_validator("measure")
    @classmethod
    def _measure(cls, v: str) -> str:
        if v not in MEASURES:
            raise ValueError(f"Medida inválida: {v}")
        return v

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        if v not in UNITS:
            raise ValueError(f"Unidad inválida: {v}")
        return v

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in MODES:
            raise ValueError(f"Modo inválido: {v}")
        return v

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [" ".join(k.split()) for k in v if k and k.strip()]


class RuleRead(RuleIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    keywords: list[str]


class RuleSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    # Si viene, duplica ese juego (reglas incluidas); si no, arranca vacío.
    copy_from_id: int | None = None


class RuleSetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_default: bool = False
    # Reemplaza todas las reglas (en este orden).
    rules: list[RuleIn]


class RuleSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime
    rules: list[RuleRead]
