from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.budget_rules import KINDS, LABOR_MODES, MEASURES, MODES, UNITS


class CrewMember(BaseModel):
    trade: str = Field(min_length=1, max_length=80)
    count: float = Field(gt=0, le=50)


class RuleIn(BaseModel):
    measure: str
    label: str = Field(min_length=1, max_length=120)
    # Obligatorias en reglas de material; las de mano de obra no buscan productos.
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    unit: str
    factor: float = Field(ge=0)
    mode: str = "fixed"
    waste_pct: float = Field(default=0, ge=0, le=100)
    notes: str | None = None
    kind: str = "material"
    stage: str | None = Field(default=None, max_length=64)
    daily_yield: float | None = Field(default=None, ge=0)
    labor_mode: str | None = None
    unit_price: float | None = Field(default=None, ge=0)
    crew: list[CrewMember] | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"Tipo inválido: {v}")
        return v

    @field_validator("labor_mode")
    @classmethod
    def _labor_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in LABOR_MODES:
            raise ValueError(f"Modo de mano de obra inválido: {v}")
        return v

    @model_validator(mode="after")
    def _by_kind(self):
        if self.kind == "material" and not self.keywords:
            raise ValueError(f"\"{self.label}\": falta al menos una palabra para buscar en el presupuesto.")
        if self.kind == "labor":
            self.labor_mode = self.labor_mode or "unit"
            self.unit = MEASURES[self.measure][1] if self.measure in MEASURES else self.unit
        return self

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
    is_default: bool = False  # ignorado: el predeterminado es el juego del sistema
    # Reemplaza todas las reglas (en este orden).
    rules: list[RuleIn]


class RuleSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_default: bool
    is_system: bool
    organization_id: int | None
    created_at: datetime
    updated_at: datetime
    rules: list[RuleRead]
