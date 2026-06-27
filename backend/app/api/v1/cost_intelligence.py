"""Interface (HTTP) del Motor de Inteligencia de Costos — Módulo 2.

Cablea los casos de uso del bounded context (`RunSimulation`,
`CompareScenarios`) con los adapters SQL y la auth/multi-tenancy existente.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.cost_intelligence.application.use_cases.compare_scenarios import CompareScenarios
from app.cost_intelligence.application.use_cases.run_simulation import RunSimulation
from app.cost_intelligence.infrastructure.persistence.measurement_provider import SqlMeasurementProvider
from app.cost_intelligence.infrastructure.persistence.recipe_catalog import SqlRecipeCatalog
from app.cost_intelligence.infrastructure.persistence.simulation_store import SqlSimulationStore
from app.models import Plan, Project, Simulation, User
from app.schemas.simulation import (
    CompareRequest, CompareResponse, SimulationCreate, SimulationRead,
)

router = APIRouter(tags=["cost-intelligence"])


def _assert_plan_in_org(db: Session, plan_id: int, organization_id: int) -> None:
    """Aísla por org: el plano debe pertenecer a un proyecto de la org."""
    plan = db.get(Plan, plan_id)
    project = db.get(Project, plan.project_id) if plan else None
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Plano no encontrado")


def _to_read(sim: Simulation) -> SimulationRead:
    return SimulationRead(
        id=sim.id, plan_id=sim.plan_id, name=sim.name, status=sim.status,
        created_at=sim.created_at, totals=sim.totals, lines=sim.lines,
    )


@router.post("/simulations", response_model=SimulationRead)
def create_simulation(
    payload: SimulationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SimulationRead:
    _assert_plan_in_org(db, payload.plan_id, user.organization_id)
    run = RunSimulation(SqlMeasurementProvider(db), SqlRecipeCatalog(db))
    name = payload.name or "Simulación"
    scenario = run.execute(
        payload.plan_id, user.organization_id, payload.selection,
        label=name, page=payload.page,
    )
    sim = SqlSimulationStore(db).save(user.organization_id, payload.plan_id, name, scenario)
    db.commit()
    db.refresh(sim)
    return _to_read(sim)


@router.get("/simulations", response_model=list[SimulationRead])
def list_simulations(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SimulationRead]:
    _assert_plan_in_org(db, plan_id, user.organization_id)
    sims = SqlSimulationStore(db).list_for_plan(plan_id, user.organization_id)
    return [_to_read(s) for s in sims]


@router.get("/simulations/{simulation_id}", response_model=SimulationRead)
def get_simulation(
    simulation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SimulationRead:
    sim = SqlSimulationStore(db).get(simulation_id, user.organization_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulación no encontrada")
    return _to_read(sim)


@router.post("/scenarios/compare", response_model=CompareResponse)
def compare_scenarios(
    payload: CompareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CompareResponse:
    _assert_plan_in_org(db, payload.plan_id, user.organization_id)
    run = RunSimulation(SqlMeasurementProvider(db), SqlRecipeCatalog(db))
    catalog = SqlRecipeCatalog(db)
    try:
        _, _, diff = CompareScenarios(run, catalog).execute(
            payload.plan_id, user.organization_id, payload.entity_type,
            payload.recipe_a, payload.recipe_b, page=payload.page,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return CompareResponse(
        original=diff.base_label,
        alternative=diff.alt_label,
        material_cost_difference=float(diff.material_cost_difference.amount),
        labor_cost_difference=float(diff.labor_cost_difference.amount),
        time_saved_days=float(diff.time_saved_days),
    )
