"""Presupuesto del proveedor subido a un proyecto (uno por proyecto).

Se guarda el archivo original (para re-leerlo si cambia la base de IVA) y el
resultado del lector; el presupuesto se recalcula siempre en vivo con las
medidas del IFC y el juego de reglas del proyecto, aplicando las decisiones
del usuario en la revisión (overrides y correcciones de presentación).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectPriceList(Base):
    __tablename__ = "project_price_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # None = detectar; True/False = forzado por el usuario.
    iva_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parsed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # item_key → row elegido a mano (None = sin precio a propósito).
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # row (str) → {"amount": float, "unit": str}: corrige la presentación leída.
    line_patches: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
