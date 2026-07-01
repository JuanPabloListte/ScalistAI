"""Configuración de costos indirectos por organización.

Las tasas (gastos generales, beneficio, IVA) que convierten el costo directo en
precio de venta. Una fila por org; el repo crea defaults si no existe.
"""
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CostSettings(Base):
    __tablename__ = "cost_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    overhead_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)  # gastos generales
    profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.10)    # beneficio
    iva_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.21)
    # Rubros paramétricos: lo que el modelo NO trae (fundaciones, instalaciones,
    # terminaciones) estimado como % sobre la obra gris. Lista de {key,label,pct}.
    # None = usar defaults del repo. Editable por org.
    parametric_rubros: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
