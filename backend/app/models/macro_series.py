"""Series macroeconómicas: índices oficiales para el motor predictivo.

ICC (Índice del Costo de la Construcción, INDEC), IPC, dólar oficial/paralelo.
Son datos REALES de fuente oficial (no inventados): se ingestan vía API INDEC/
BCRA o carga manual. El `MacroRateProvider` deriva de acá la tasa mensual para
la proyección determinística (Vía A); el ML (Vía B) los usará como features.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MacroSeries(Base):
    __tablename__ = "macro_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator: Mapped[str] = mapped_column(String(40), nullable=False)  # "ICC","IPC","dolar_oficial","dolar_blue"
    value: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")

    __table_args__ = (Index("ix_macro_indicator_date", "indicator", "date"),)
