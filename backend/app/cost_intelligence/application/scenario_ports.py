"""Puertos del simulador de escenarios.

`MeasurementProvider` y `RecipeCatalog` son la capa anti-corrupción: traducen
los modelos existentes (DetectedElement, Assembly, AssemblyMaterial, Material)
al lenguaje del dominio (ElementMeasurement, Recipe). Los casos de uso dependen
de estas interfaces, no de SQLAlchemy → testeables con fakes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.cost_intelligence.domain.scenario import ElementMeasurement, Recipe


class MeasurementProvider(ABC):
    @abstractmethod
    def measurements_for(self, plan_id: int, page: Optional[int] = None) -> list[ElementMeasurement]:
        """Mediciones del plano (un ElementMeasurement por elemento computable)."""


class RecipeCatalog(ABC):
    @abstractmethod
    def recipe(self, recipe_id: int) -> Optional[Recipe]:
        """Receta completa (con componentes y precios vigentes), o None."""

    @abstractmethod
    def default_recipe(self, organization_id: int, entity_type: str) -> Optional[Recipe]:
        """Receta default (is_default_alternative) de la entidad, o None."""
