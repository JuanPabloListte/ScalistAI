from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.detected_element import DetectedElement
    from app.models.project import Project
    from app.models.plan_ai_context import PlanAiContext


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    raster_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scale_px_per_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    scale_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # dict { "1": 59.06, "2": 78.74, ... } — escala px/m por número de página (1-indexed)
    page_scales: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # list [1, 2, ...] — páginas eliminadas (1-indexed)
    deleted_pages: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # dict { "<page>": "recommended" | "rejected" } — overrides manuales del
    # usuario que sobreescriben la recomendacion del algoritmo.
    page_overrides: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    # dict { "<page>": ["walls", "openings", "rooms"] } — rol(es) que cumple
    # cada pagina para la deteccion automatica. Una pagina sin entrada (o con
    # lista vacia) no se procesa. Permite que un mismo plano use diferentes
    # paginas para muros, aberturas y recintos, en lugar de correr todo sobre
    # las mismas paginas.
    page_roles: Mapped[dict[str, list[str]] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="plans")
    detected_elements: Mapped[list["DetectedElement"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    ai_context: Mapped["PlanAiContext"] = relationship(
        back_populates="plan", cascade="all, delete-orphan", uselist=False
    )

