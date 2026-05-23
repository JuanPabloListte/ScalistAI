from typing import TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, String, Float, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.detected_element import DetectedElement

# Tabla de asociación muchos-a-muchos
element_materials = Table(
    "element_materials",
    Base.metadata,
    Column("element_id", ForeignKey("detected_elements.id", ondelete="CASCADE"), primary_key=True),
    Column("material_id", ForeignKey("materials.id", ondelete="CASCADE"), primary_key=True),
)

class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "Mampostería", "Pintura", "Pisos", "Zócalos"
    unit: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g., "un", "m2", "l", "ml"

    yields: Mapped[list["MaterialYield"]] = relationship(
        "MaterialYield", back_populates="material", cascade="all, delete-orphan"
    )

    elements: Mapped[list["DetectedElement"]] = relationship(
        "DetectedElement", secondary="element_materials", back_populates="materials"
    )


class MaterialYield(Base):
    __tablename__ = "material_yields"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    applies_to: Mapped[str] = mapped_column(String(32), nullable=False)  # "wall", "room_floor", "room_wall", "room_perimeter"
    consumption: Mapped[float] = mapped_column(Float, nullable=False)
    waste_factor: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    material: Mapped["Material"] = relationship("Material", back_populates="yields")
