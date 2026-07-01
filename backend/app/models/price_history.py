"""Histórico de precios de materiales (serie temporal).

Base del motor predictivo. Diseñada **hypertable-ready** para migrar a
TimescaleDB en Fase 4: columna temporal `date` = timestamptz, índice
`(material_id, date)`. El precio vigente sigue cacheado en `Material.unit_price`
(lo que consume el motor de cómputo actual); el repo lo mantiene sincronizado.

Nota Timescale (Fase 4): al convertir en hypertable, la PK deberá incluir
`date`. Por ahora (Postgres plano) un `id` surrogate alcanza.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MaterialPriceHistory(Base):
    __tablename__ = "material_price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")

    __table_args__ = (Index("ix_mph_material_date", "material_id", "date"),)
