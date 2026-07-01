"""Persistencia del read-model de simulaciones. Serializa el `Scenario` del
dominio a JSON y lo guarda/recupera. Read-model → no necesita puerto abstracto.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cost_intelligence.domain.scenario import Scenario
from app.models.simulation import Simulation


def scenario_payload(scenario: Scenario) -> tuple[dict, list[dict]]:
    """`Scenario` (dominio, Decimals/Money) → (totals_dict, lines_list) JSON-safe."""
    t = scenario.totals
    totals = {
        "materials": float(t.materials.amount),
        "labor_cost": float(t.labor_cost.amount),
        "labor_hours": float(t.labor_hours),
        "duration_days": float(t.duration_days),
    }
    lines = [
        {
            "material_id": ln.material_id,
            "material_name": ln.material_name,
            "quantity": float(ln.quantity.value),
            "unit": ln.quantity.unit,
            "unit_cost": float(ln.unit_cost.amount),
            "total": float(ln.total.amount),
        }
        for ln in scenario.lines
    ]
    return totals, lines


class SqlSimulationStore:
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, organization_id: int, plan_id: int, name: str, scenario: Scenario) -> Simulation:
        totals, lines = scenario_payload(scenario)
        sim = Simulation(
            organization_id=organization_id,
            plan_id=plan_id,
            name=name,
            status="done",
            totals=totals,
            lines=lines,
        )
        self._s.add(sim)
        self._s.flush()
        return sim

    def get(self, simulation_id: int, organization_id: int) -> Optional[Simulation]:
        sim = self._s.get(Simulation, simulation_id)
        if sim is None or sim.organization_id != organization_id:
            return None
        return sim

    def list_for_plan(self, plan_id: int, organization_id: int) -> list[Simulation]:
        return list(self._s.scalars(
            select(Simulation)
            .where(Simulation.plan_id == plan_id,
                   Simulation.organization_id == organization_id)
            .order_by(Simulation.created_at.desc())
        ).all())
