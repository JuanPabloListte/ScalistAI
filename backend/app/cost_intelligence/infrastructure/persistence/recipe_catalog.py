"""Adapter anti-corrupción: traduce `Assembly` + `AssemblyMaterial` + `Material`
a la `Recipe` del dominio (con sus componentes y precio vigente). Marca como
mano de obra los componentes de categoría "Recursos Humanos".
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.application.scenario_ports import RecipeCatalog
from app.cost_intelligence.domain.scenario import Recipe, RecipeComponent
from app.cost_intelligence.domain.value_objects import Money
from app.models.material import Assembly

_LABOR_CATEGORY = "Recursos Humanos"


def _dec(value: Optional[float]) -> Decimal:
    return Decimal(str(value or 0))


def _to_recipe(assembly: Assembly) -> Recipe:
    components = tuple(
        RecipeComponent(
            material_id=am.material.id,
            material_name=am.material.name,
            consumption=_dec(am.consumption),
            waste=_dec(am.waste_factor),
            unit_price=Money(am.material.unit_price or 0.0),
            unit=am.material.unit or "un",
            is_labor=(am.material.category == _LABOR_CATEGORY),
        )
        for am in assembly.assembly_materials
    )
    return Recipe(
        id=assembly.id,
        name=assembly.name,
        entity_type=assembly.applies_to,
        daily_yield=_dec(assembly.daily_yield),
        components=components,
    )


class SqlRecipeCatalog(RecipeCatalog):
    def __init__(self, session: Session) -> None:
        self._s = session

    def recipe(self, recipe_id: int) -> Optional[Recipe]:
        assembly = self._s.get(Assembly, recipe_id)
        return _to_recipe(assembly) if assembly is not None else None

    def default_recipe(self, organization_id: int, entity_type: str) -> Optional[Recipe]:
        assembly = self._s.scalars(
            select(Assembly).where(
                Assembly.organization_id == organization_id,
                Assembly.applies_to == entity_type,
                Assembly.is_default_alternative.is_(True),
            ).limit(1)
        ).first()
        return _to_recipe(assembly) if assembly is not None else None
