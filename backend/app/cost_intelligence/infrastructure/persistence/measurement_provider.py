"""Adapter anti-corrupción: traduce `DetectedElement` (geometría del CAD) a
`ElementMeasurement` del dominio. Mapea el tipo de elemento a su entidad
constructiva (= applies_to) y descarta candidatos sin aprobar.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.application.scenario_ports import MeasurementProvider
from app.cost_intelligence.domain.measurement import ElementGeometry
from app.cost_intelligence.domain.scenario import ElementMeasurement
from app.models.detected_element import DetectedElement

# tipo de DetectedElement -> entity_type (applies_to). Las aberturas (door/
# window/sliding_door) se computan como "opening". Tipos no listados se ignoran.
_TYPE_TO_ENTITY = {
    "wall": "wall",
    "room": "room_floor",
    "opening": "opening",
    "door": "opening",
    "window": "opening",
    "sliding_door": "opening",
    "beam": "beam",
    "column": "column",
    "roof": "roof",
    "riostra": "riostra",
    "cloaca": "cloaca",
    "electricidad": "electricidad",
    "escalera": "escalera",
    "pozo": "pozo",
}


class SqlMeasurementProvider(MeasurementProvider):
    def __init__(self, session: Session) -> None:
        self._s = session

    def measurements_for(self, plan_id: int, page: Optional[int] = None) -> list[ElementMeasurement]:
        stmt = select(DetectedElement).where(
            DetectedElement.plan_id == plan_id,
            DetectedElement.is_candidate.is_(False),
        )
        if page is not None:
            stmt = stmt.where(DetectedElement.page == page)

        out: list[ElementMeasurement] = []
        for el in self._s.scalars(stmt):
            entity_type = _TYPE_TO_ENTITY.get(el.type)
            if entity_type is None:
                continue
            out.append(ElementMeasurement(
                entity_type=entity_type,
                geometry=ElementGeometry(
                    length_m=el.length_m, area_m2=el.area_m2, height_m=el.height_m,
                ),
            ))
        return out
