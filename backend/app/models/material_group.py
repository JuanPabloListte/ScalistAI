"""Producto canónico: agrupa `Material` equivalentes provenientes de distintas
fuentes/fechas (ej. "Cemento Holcim 50kg" de Cormac-2022 + de Carignani-2025)
bajo un solo producto, para unir sus precios en UNA serie temporal real.

El match NO es automático: el motor propone candidatos y un humano los aprueba
(misma filosofía que la detección). Un Material pertenece a ≤1 grupo.
"""
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.material import Material


class MaterialGroup(Base):
    __tablename__ = "material_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="un")

    members: Mapped[list["Material"]] = relationship(
        "Material", back_populates="group")
