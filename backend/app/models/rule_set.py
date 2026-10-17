"""Juegos de reglas de cómputo: cómo se pasa del modelo IFC a productos.

Cada regla toma una MEDIDA del modelo (m² de muro, m³ de columnas, kg de
armadura...) y la convierte en cantidad de un PRODUCTO que se busca por
palabras clave en el presupuesto del proveedor. Independiente del catálogo
viejo de insumos/sistemas (materials/assemblies).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class RuleSet(Base):
    __tablename__ = "rule_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = juego global del sistema ("Estándar Argentina"): lo ven todas
    # las orgs y solo lo edita el superadmin.
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # El que se preselecciona al crear un proyecto: el juego del sistema.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    organization: Mapped["Organization | None"] = relationship()
    rules: Mapped[list["Rule"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan",
        order_by="Rule.position",
    )


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("rule_sets.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Clave de services.budget_rules.MEASURES (muro_m2, columna_m3, armadura_kg...).
    measure: Mapped[str] = mapped_column(String(32), nullable=False)
    # Nombre del producto en el presupuesto ("Cemento", "Ladrillo portante 12").
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # Frases a buscar en la descripción del proveedor: basta que matchee UNA;
    # dentro de la frase deben aparecer TODAS las palabras.
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Unidad del producto en la que se expresa el factor: kg, m3, u, m, l, m2.
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    factor: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # fixed: medida × factor. brick_dims: unidades/m² según medidas del
    # ladrillo del proveedor (factor = respaldo). rebar: un ítem por diámetro.
    mode: Mapped[str] = mapped_column(String(16), default="fixed", nullable=False)
    waste_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule_set: Mapped[RuleSet] = relationship(back_populates="rules")
