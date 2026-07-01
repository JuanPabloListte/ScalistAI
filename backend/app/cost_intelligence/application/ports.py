"""Puertos: interfaces que la aplicación necesita y la infraestructura implementa.

Invierten la dependencia (los casos de uso dependen de la abstracción, no de
SQLAlchemy) → se testean con repos fake in-memory, sin DB.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from app.cost_intelligence.domain.labor import LaborRatePoint
from app.cost_intelligence.domain.pricing import PricePoint


class PriceHistoryRepository(ABC):
    """Persistencia del histórico de precios de materiales."""

    @abstractmethod
    def add(self, point: PricePoint) -> PricePoint:
        """Agrega un punto al histórico y sincroniza el precio vigente."""

    @abstractmethod
    def latest(self, material_id: int) -> Optional[PricePoint]:
        """Último precio conocido del material, o None."""

    @abstractmethod
    def series(self, material_id: int, since: Optional[date] = None) -> list[PricePoint]:
        """Serie histórica ascendente por fecha, opcionalmente desde `since`."""

    @abstractmethod
    def has_history(self, material_id: int) -> bool:
        """True si el material ya tiene al menos un punto (para backfill idempotente)."""


class LaborRateHistoryRepository(ABC):
    """Persistencia del histórico de costos de mano de obra (por oficio)."""

    @abstractmethod
    def add(self, point: LaborRatePoint) -> LaborRatePoint:
        """Agrega un punto al histórico y sincroniza el costo diario vigente."""

    @abstractmethod
    def latest(self, labor_rate_id: int) -> Optional[LaborRatePoint]:
        """Último costo diario conocido del oficio, o None."""

    @abstractmethod
    def series(self, labor_rate_id: int, since: Optional[date] = None) -> list[LaborRatePoint]:
        """Serie histórica ascendente por fecha, opcionalmente desde `since`."""

    @abstractmethod
    def has_history(self, labor_rate_id: int) -> bool:
        """True si el oficio ya tiene al menos un punto (para backfill idempotente)."""
