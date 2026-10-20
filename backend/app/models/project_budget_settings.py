"""Ajustes del presupuesto de un proyecto (uno por proyecto).

Lo que el usuario decide para ESTA obra sobre lo que traen las reglas:
cómo se cotiza cada rubro de mano de obra (tercerizado o cuadrilla propia,
con el precio del contratista de esta obra) y los márgenes, si difieren de
los de la empresa.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectBudgetSettings(Base):
    __tablename__ = "project_budget_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    # rule_id (str) → {"mode": "unit"|"daily", "unit_price": float|None}
    labor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # None = usar los de la empresa (cost_settings).
    overhead_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
