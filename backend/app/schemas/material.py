from pydantic import BaseModel, ConfigDict, Field

class MaterialYieldBase(BaseModel):
    applies_to: str = Field(..., pattern="^(wall|room_floor|room_wall|room_perimeter|opening|opening_perimeter)$")
    consumption: float = Field(..., ge=0)
    waste_factor: float = Field(..., ge=0)
    unit_price: float = Field(0.0, ge=0)

class MaterialYieldCreate(MaterialYieldBase):
    pass

class MaterialYieldRead(MaterialYieldBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int

class MaterialBase(BaseModel):
    name: str
    category: str
    unit: str

class MaterialCreate(MaterialBase):
    yields: list[MaterialYieldCreate] = []

class MaterialUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    yields: list[MaterialYieldCreate] | None = None

class MaterialRead(MaterialBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    yields: list[MaterialYieldRead] = []


class MaterialAssignRequest(BaseModel):
    material_id: int


class MaterialSummaryItem(BaseModel):
    material: MaterialRead
    quantity: float
    unit: str
    unit_price: float
    subtotal: float


class MaterialPriceUpdateRequest(BaseModel):
    unit_price: float = Field(..., ge=0)


class MaterialBulkAssignRequest(BaseModel):
    element_ids: list[int] = Field(..., min_items=1)
    material_id: int


class MaterialBulkRemoveRequest(BaseModel):
    element_ids: list[int] = Field(..., min_items=1)
    material_id: int
