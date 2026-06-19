from typing import TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, Integer, String, Float, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.detected_element import DetectedElement

# Material en crudo (ej: "Ladrillo hueco 15cm", "Cemento portland", "Arena")
class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "Mampostería", "Aglomerantes", "Áridos"
    unit: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g., "un", "kg", "m3", "l"
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    assembly_materials: Mapped[list["AssemblyMaterial"]] = relationship(
        "AssemblyMaterial", back_populates="material", cascade="all, delete-orphan"
    )

# Sistema Constructivo / Ensamblaje (ej: "Muro Ladrillo Hueco 15cm c/ Revoque")
# Se asigna a un elemento (ej: "wall", "room", "roof")
element_assemblies = Table(
    "element_assemblies",
    Base.metadata,
    Column("element_id", ForeignKey("detected_elements.id", ondelete="CASCADE"), primary_key=True),
    Column("assembly_id", ForeignKey("assemblies.id", ondelete="CASCADE"), primary_key=True),
)

class Assembly(Base):
    __tablename__ = "assemblies"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Define a qué se aplica (ej: "wall", "room_floor", "room_wall", "room_perimeter", "opening", "beam", "column", "roof")
    applies_to: Mapped[str] = mapped_column(String(32), nullable=False)
    # Rendimiento diario de este sistema (ej: m2 por día). Usado para Gantt.
    daily_yield: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    # Rubro / etapa de obra (ej: "Fundación", "Estructura", "Mampostería",
    # "Instalaciones", "Terminaciones") y su orden. Agrupan el cómputo para el
    # cronograma (Gantt) y la certificación de avance.
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")

    assembly_materials: Mapped[list["AssemblyMaterial"]] = relationship(
        "AssemblyMaterial", back_populates="assembly", cascade="all, delete-orphan"
    )

    elements: Mapped[list["DetectedElement"]] = relationship(
        "DetectedElement", secondary=element_assemblies, back_populates="assemblies"
    )

class AssemblyMaterial(Base):
    __tablename__ = "assembly_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    assembly_id: Mapped[int] = mapped_column(ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    
    # Rendimiento: cantidad del material base requerida por 1 unidad de Assembly (que suele medirse en la unidad del elemento: m2, ml, un)
    # Por ejemplo, un Muro (m2) requiere 15 Ladrillos (unidades). Entonces consumption = 15.0
    consumption: Mapped[float] = mapped_column(Float, nullable=False)
    waste_factor: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    assembly: Mapped["Assembly"] = relationship("Assembly", back_populates="assembly_materials")
    material: Mapped["Material"] = relationship("Material", back_populates="assembly_materials")
