"""Catálogo de entidades constructivas (muro, losa, cubierta, contrapiso…).

Formaliza lo que hoy es un string suelto (`Assembly.applies_to`): cada entidad
agrupa sus **recetas alternativas** (ej. Muro → Ladrillo / Durlock / Retak), lo
que habilita el simulador de escenarios. Es per-organización.

El `type` mapea 1:1 con `applies_to` ("wall","roof","beam"…) para integrarse sin
fricción con el motor de cómputo existente; `unit` sale del contrato de medición
del dominio (`cost_intelligence.domain.measurement.unit_for`).
"""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.material import Assembly


class ConstructionEntity(Base):
    __tablename__ = "construction_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)   # "Muro", "Techo / Losa"
    type: Mapped[str] = mapped_column(String(32), nullable=False)    # = applies_to ("wall","roof")
    unit: Mapped[str] = mapped_column(String(16), nullable=False)    # "m2", "ml"
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)

    # Recetas (assemblies) que son alternativas de esta entidad.
    recipes: Mapped[list["Assembly"]] = relationship(
        "Assembly", back_populates="construction_entity"
    )
