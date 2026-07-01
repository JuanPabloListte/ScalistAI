"""Simulaciones materializadas (read-model).

Una `Simulation` guarda el resultado de correr un escenario sobre un plano:
totales (materiales, mano de obra, duración) + líneas de material, como JSON.
Se materializa para no recomputar en cada lectura y para alimentar el export
(Módulo 5). Es per-organización.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="Simulación")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="done")
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)   # {materials, labor_cost, labor_hours, duration_days}
    lines: Mapped[list] = mapped_column(JSON, nullable=False)    # [{material_id, material_name, quantity, unit, unit_cost, total}]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
