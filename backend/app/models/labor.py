"""Mano de obra first-class: oficios (trades) con su costo diario + histórico.

Hoy la mano de obra está modelada como un `Material` ("Mano de Obra Ayudante",
unidad hs) referenciado por las recetas. Estas tablas la promueven a concepto
propio (costo por día por oficio) con serie temporal — habilita el
`labor_cost_difference` del simulador y el proyectado de salarios.

NO-BREAKING: el material sigue existiendo y las recetas lo siguen usando; el
rewire de recetas a `labor_rates` es de una fase posterior.
"""
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, String,
                        func, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LaborRate(Base):
    __tablename__ = "labor_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade: Mapped[str] = mapped_column(String(80), nullable=False)  # "Ayudante", "Oficial", "Capataz"
    daily_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # cache costo vigente
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)

    history: Mapped[list["LaborRateHistory"]] = relationship(
        "LaborRateHistory", back_populates="labor_rate", cascade="all, delete-orphan"
    )


class LaborRateHistory(Base):
    __tablename__ = "labor_rate_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    labor_rate_id: Mapped[int] = mapped_column(
        ForeignKey("labor_rates.id", ondelete="CASCADE"), nullable=False
    )
    daily_cost: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")

    labor_rate: Mapped["LaborRate"] = relationship("LaborRate", back_populates="history")

    __table_args__ = (Index("ix_lrh_rate_date", "labor_rate_id", "date"),)
