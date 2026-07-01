"""Proyección de precio por material a partir de su SERIE PROPIA (Vía B-lite).

Idea (la del usuario): si tengo en mi base que el hormigón valía X hace 3 meses
y hoy vale Y, calculo la tasa a la que viene subiendo y proyecto a futuro.

    tasa_mensual = (precio_último / precio_primero) ^ (1 / meses) − 1
    proyectado   = precio_último × (1 + tasa_mensual) ^ horizonte

Honestidad / reglas:
- **≥2 puntos** en fechas distintas → uso la tasa OBSERVADA del material
  (`method="serie_propia"`). Es lo que el usuario realmente vio, no inventado.
- **<2 puntos** → caigo a la tasa macro IPC (`method="ipc"`); si tampoco hay
  IPC, no proyecto (`method="sin_dato"`, tasa 0).
- Siempre informo **cuántos puntos** respaldan la tasa (confianza) y la **tasa
  IPC** para comparar ("tu material sube más/menos que la inflación").

Es determinístico y explicable. Cuando la serie tenga densidad, una regresión /
ML reemplaza el cálculo de la tasa sin cambiar este contrato (mismo TrendForecast).
Trabaja en float: es una PROYECCIÓN analítica para mostrar, no aritmética de
dinero autoritativa (esa vive en `Money`/Decimal).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

_DAYS_PER_MONTH = 30.4375

METHOD_OWN = "serie_propia"
METHOD_IPC = "ipc"
METHOD_NONE = "sin_dato"


@dataclass(frozen=True, slots=True)
class TrendForecast:
    last_price: float
    horizon_months: int
    monthly_rate: float            # tasa usada para proyectar
    projected_price: float
    method: str                    # serie_propia | ipc | sin_dato
    n_points: int                  # nº de fechas DISTINTAS que respaldan la tasa
    ipc_monthly_rate: float | None  # tasa IPC, para comparar

    @property
    def variation_pct(self) -> float:
        if self.last_price == 0:
            return 0.0
        return (self.projected_price / self.last_price - 1.0) * 100.0

    @property
    def beats_inflation(self) -> bool | None:
        """True si el material sube MÁS rápido que el IPC (None si no aplica)."""
        if self.method != METHOD_OWN or self.ipc_monthly_rate is None:
            return None
        return self.monthly_rate > self.ipc_monthly_rate


def _consolidate(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """1 precio por fecha (media), ordenado — evita que varias cotizaciones del
    mismo día (varios proveedores) cuenten como puntos de tendencia distintos."""
    by_date: dict[date, list[float]] = defaultdict(list)
    for d, p in points:
        by_date[d].append(p)
    return sorted((d, sum(v) / len(v)) for d, v in by_date.items())


def project_material(
    points: list[tuple[date, float]],
    horizon_months: int,
    ipc_monthly_rate: float | None,
) -> TrendForecast:
    if horizon_months <= 0:
        raise ValueError("El horizonte debe ser de al menos 1 mes")
    if not points:
        raise ValueError("Se requiere al menos un punto de precio")

    series = _consolidate(points)
    last_price = series[-1][1]
    n = len(series)

    rate: float
    method: str
    if n >= 2:
        (d0, p0), (d1, p1) = series[0], series[-1]
        months = (d1 - d0).days / _DAYS_PER_MONTH
        if months > 0 and p0 > 0:
            rate = (p1 / p0) ** (1.0 / months) - 1.0
            method = METHOD_OWN
        elif ipc_monthly_rate is not None:
            rate, method = ipc_monthly_rate, METHOD_IPC
        else:
            rate, method = 0.0, METHOD_NONE
    elif ipc_monthly_rate is not None:
        rate, method = ipc_monthly_rate, METHOD_IPC
    else:
        rate, method = 0.0, METHOD_NONE

    projected = last_price * (1.0 + rate) ** horizon_months
    return TrendForecast(
        last_price=last_price,
        horizon_months=horizon_months,
        monthly_rate=rate,
        projected_price=projected,
        method=method,
        n_points=n,
        ipc_monthly_rate=ipc_monthly_rate,
    )
