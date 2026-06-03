from pydantic import BaseModel, ConfigDict, Field

class MaterialBase(BaseModel):
    name: str
    category: str
    unit: str
    unit_price: float = Field(0.0, ge=0)

class MaterialCreate(MaterialBase):
    pass

class MaterialUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    unit_price: float | None = None

class MaterialRead(MaterialBase):
    model_config = ConfigDict(from_attributes=True)
    id: int

class MaterialSummaryItem(BaseModel):
    material: MaterialRead
    quantity: float
    unit: str
    unit_price: float
    subtotal: float
