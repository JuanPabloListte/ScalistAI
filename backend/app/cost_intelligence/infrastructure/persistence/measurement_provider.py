"""Adapter anti-corrupción: traduce `DetectedElement` (geometría del CAD) a
`ElementMeasurement` del dominio. Mapea el tipo de elemento a su entidad
constructiva (= applies_to) y descarta candidatos sin aprobar.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.cost_intelligence.application.scenario_ports import MeasurementProvider
from app.cost_intelligence.domain.measurement import ElementGeometry
from app.cost_intelligence.domain.scenario import ElementMeasurement
from app.models.detected_element import DetectedElement

# tipo de DetectedElement -> entity_types (applies_to) que GENERA. Casi todos
# 1:1, pero un `room` se EXPANDE en sus terminaciones: piso (área), cielorraso
# (área), revoque+pintura interior de muros (perímetro × altura) y zócalo
# (perímetro). Cada una mide distinto vía `measure_for`. Aberturas -> opening.
# Tipos no listados se ignoran.
_TYPE_TO_ENTITIES: dict[str, tuple[str, ...]] = {
    "wall": ("wall",),
    "room": ("room_floor", "room_ceiling", "room_wall", "room_perimeter"),
    "opening": ("opening",),
    "door": ("opening",),
    "window": ("opening",),
    "sliding_door": ("opening",),
    "beam": ("beam",),
    "column": ("column",),
    "roof": ("roof",),
    "riostra": ("riostra",),
    "cloaca": ("cloaca",),
    "electricidad": ("electricidad",),
    "escalera": ("escalera",),
    "pozo": ("pozo",),
    "sanitario": ("sanitario",),
    "boca_electrica": ("boca_electrica",),
}


class SqlMeasurementProvider(MeasurementProvider):
    def __init__(self, session: Session) -> None:
        self._s = session

    def measurements_for(self, plan_id: int, page: Optional[int] = None) -> list[ElementMeasurement]:
        stmt = select(DetectedElement).where(
            DetectedElement.plan_id == plan_id,
            DetectedElement.is_candidate.is_(False),
        ).options(selectinload(DetectedElement.assemblies))
        if page is not None:
            stmt = stmt.where(DetectedElement.page == page)

        out: list[ElementMeasurement] = []
        room_area_sum = 0.0
        has_roof = False
        for el in self._s.scalars(stmt):
            geom = ElementGeometry(
                length_m=el.length_m, area_m2=el.area_m2, height_m=el.height_m,
            )
            # Receta asignada a ESTE elemento, por applies_to (override del default).
            assigned = {a.applies_to: a.id for a in el.assemblies}
            if el.type == "roof":
                has_roof = True
            elif el.type == "room" and el.area_m2:
                room_area_sum += el.area_m2
            for entity_type in _TYPE_TO_ENTITIES.get(el.type, ()):
                out.append(ElementMeasurement(
                    entity_type=entity_type, geometry=geom,
                    recipe_id=assigned.get(entity_type)))

        # Cubierta/losa DERIVADA: en los DXF reales el techo no está dibujado como
        # polígono cerrado (son arcos/líneas), así que no se puede extraer. Si no
        # hay techo explícito pero sí ambientes, se estima el área de losa como la
        # huella = suma de las áreas de los `room`. Así el rubro cubierta (membrana,
        # viguetas, bovedillas, H°) deja de faltar. (Multi-piso: suma todas las
        # plantas presentes en el alcance pedido; es una estimación, no medición.)
        if not has_roof and room_area_sum > 0:
            out.append(ElementMeasurement(
                entity_type="roof",
                geometry=ElementGeometry(area_m2=room_area_sum),
            ))
        return out
