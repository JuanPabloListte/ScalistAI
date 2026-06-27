"""DTOs del motor predictivo (Módulo 3)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ForecastRequest(BaseModel):
    # qué proyectar: una simulación persistida, o un monto suelto
    simulation_id: Optional[int] = None
    amount: Optional[float] = None
    horizon_months: int
    # tasa mensual explícita (ej. 0.05 = 5%/mes). Si falta, se deriva del índice.
    monthly_rate: Optional[float] = None
    indicator: str = "ICC"


class ForecastResponse(BaseModel):
    """Coincide con el ejemplo del Módulo 3 de la propuesta."""
    cost_today: float
    projected_cost: float
    variation: float          # %
    horizon_months: int
    monthly_rate: float
    method: str
