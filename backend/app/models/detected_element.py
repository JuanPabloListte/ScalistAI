from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.plan import Plan
    from app.models.material import Assembly


class DetectedElement(Base):
    __tablename__ = "detected_elements"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # "wall", "room", "opening", "column", "beam", "roof", "riostra", "cloaca", "electricidad"
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_m: Mapped[float | None] = mapped_column(Float, default=2.8, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)  # ver ElementSource en schemas/detected_element.py
    # Propuesta de la IA pendiente de aprobación: no computa metros ni materiales
    # hasta que el usuario la acepte (pasa a is_candidate=False).
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # 0.0–1.0; los elementos vectoriales (CAD) y manuales siempre quedan en 1.0.
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0", nullable=False)
    # Nivel/piso del elemento (IfcBuildingStorey en BIM): "Planta Baja", "P1"...
    # level_order = índice por elevación (0 = más bajo) para ordenar tareas por
    # nivel en el cronograma. NULL en fuentes sin nivel (PDF/DXF/manual).
    level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["Plan"] = relationship(back_populates="detected_elements")
    assemblies: Mapped[list["Assembly"]] = relationship(
        secondary="element_assemblies", back_populates="elements"
    )

