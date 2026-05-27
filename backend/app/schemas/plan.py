from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    original_filename: str
    page: int
    page_count: int | None
    status: str
    dpi: int | None
    scale_px_per_m: float | None
    scale_source: str | None
    page_scales: dict[str, float] | None
    deleted_pages: list[int] | None = None
    page_overrides: dict[str, str] | None = None
    created_at: datetime


class Point(BaseModel):
    x: float
    y: float


class ScaleCalibration(BaseModel):
    p1: Point
    p2: Point
    real_distance_m: float = Field(gt=0, le=10000)
    page: int = Field(default=1, ge=1)


class ScaleByRatio(BaseModel):
    page: int = Field(ge=1)
    denominator: float = Field(gt=0, le=10000, description="N en una escala 1:N")


class ScaleDirect(BaseModel):
    page: int = Field(ge=1)
    px_per_m: float = Field(gt=0, description="px_per_m ya calculado (típicamente mediana de varias referencias)")
    source: str = Field(default="manual_multi", max_length=32)
