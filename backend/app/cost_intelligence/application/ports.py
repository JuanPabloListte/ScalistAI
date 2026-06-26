"""Puertos: interfaces que la aplicación necesita y la infraestructura implementa.

Invierten la dependencia (los casos de uso dependen de la abstracción, no de
SQLAlchemy) → se testean con repos fake in-memory, sin DB.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

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
