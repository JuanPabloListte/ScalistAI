"""Interface (HTTP) del Motor de Inteligencia de Costos — Módulo 2.

Cablea los casos de uso del bounded context (`RunSimulation`,
`CompareScenarios`) con los adapters SQL y la auth/multi-tenancy existente.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.cost_intelligence.application.use_cases.compare_scenarios import CompareScenarios
from app.cost_intelligence.application.use_cases.forecast_cost import ForecastCost
from app.cost_intelligence.application.use_cases.run_simulation import RunSimulation
from app.cost_intelligence.domain.value_objects import Money
from app.cost_intelligence.infrastructure.export.xlsx_exporter import build_workbook
from app.cost_intelligence.infrastructure.forecasting.deterministic import DeterministicForecaster
from app.cost_intelligence.infrastructure.persistence.macro_rate_provider import SqlMacroRateProvider
from app.cost_intelligence.infrastructure.persistence.measurement_provider import SqlMeasurementProvider
from app.cost_intelligence.infrastructure.persistence.recipe_catalog import SqlRecipeCatalog
from app.cost_intelligence.infrastructure.persistence.simulation_store import SqlSimulationStore
from app.models import Assembly, ConstructionEntity, Plan, Project, Simulation, User
from app.schemas.forecast import ForecastRequest, ForecastResponse
from app.schemas.simulation import (
    CompareRequest, CompareResponse, SimulationCreate, SimulationRead,
)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORECAST_HORIZONS = (3, 6, 12)

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


@router.post("/forecast", response_model=ForecastResponse)
def forecast(
    payload: ForecastRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ForecastResponse:
    # Costo a proyectar: una simulación persistida (materiales + MO) o un monto suelto.
    if payload.simulation_id is not None:
        sim = SqlSimulationStore(db).get(payload.simulation_id, user.organization_id)
        if sim is None:
            raise HTTPException(status_code=404, detail="Simulación no encontrada")
        amount = Money(sim.totals["materials"]) + Money(sim.totals["labor_cost"])
    elif payload.amount is not None:
        amount = Money(payload.amount)
    else:
        raise HTTPException(status_code=400, detail="Se requiere simulation_id o amount")

    # Tasa: explícita del request, o derivada del índice oficial (ICC) si está cargado.
    if payload.monthly_rate is not None:
        rate = Decimal(str(payload.monthly_rate))
    else:
        rate = SqlMacroRateProvider(db).monthly_rate(payload.indicator)
        if rate is None:
            raise HTTPException(
                status_code=400,
                detail=f"No hay histórico de {payload.indicator} cargado; pasá monthly_rate",
            )

    try:
        result = ForecastCost(DeterministicForecaster(rate)).execute(amount, payload.horizon_months)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ForecastResponse(
        cost_today=float(result.cost_today.amount),
        projected_cost=float(result.projected_cost.amount),
        variation=round(float(result.variation_pct), 2),
        horizon_months=result.horizon_months,
        monthly_rate=float(result.monthly_rate),
        method=result.method,
    )


def _build_scenarios(db: Session, plan_id: int, org_id: int) -> list[dict]:
    """Para cada entidad presente en el plano con >1 receta, compara la default
    contra cada alternativa → filas de la hoja 'Escenarios'."""
    run = RunSimulation(SqlMeasurementProvider(db), SqlRecipeCatalog(db))
    catalog = SqlRecipeCatalog(db)
    entity_names = {
        e.type: e.name
        for e in db.scalars(select(ConstructionEntity).where(
            ConstructionEntity.organization_id == org_id))
    }
    present = {m.entity_type for m in SqlMeasurementProvider(db).measurements_for(plan_id)}

    rows: list[dict] = []
    for entity_type in sorted(present):
        recipes = db.scalars(select(Assembly).where(
            Assembly.organization_id == org_id,
            Assembly.applies_to == entity_type,
        )).all()
        if len(recipes) < 2:
            continue
        default = next((r for r in recipes if r.is_default_alternative), recipes[0])
        for alt in recipes:
            if alt.id == default.id:
                continue
            _, _, diff = CompareScenarios(run, catalog).execute(
                plan_id, org_id, entity_type, default.id, alt.id)
            rows.append({
                "entity": entity_names.get(entity_type, entity_type),
                "base": diff.base_label,
                "alternative": diff.alt_label,
                "material_diff": float(diff.material_cost_difference.amount),
                "labor_diff": float(diff.labor_cost_difference.amount),
                "time_saved": float(diff.time_saved_days),
            })
    return rows


def _build_projections(db: Session, total: Money) -> list[dict]:
    rate = SqlMacroRateProvider(db).monthly_rate("IPC")
    if rate is None:
        return []
    out = []
    for h in _FORECAST_HORIZONS:
        r = ForecastCost(DeterministicForecaster(rate)).execute(total, h)
        out.append({
            "horizon_months": h,
            "projected_cost": float(r.projected_cost.amount),
            "variation": float(r.variation_pct),
        })
    return out


@router.get("/export/{simulation_id}")
def export_simulation(
    simulation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    sim = SqlSimulationStore(db).get(simulation_id, user.organization_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulación no encontrada")

    sim_data = {"name": sim.name, "totals": sim.totals, "lines": sim.lines}
    total = Money(sim.totals["materials"]) + Money(sim.totals["labor_cost"])
    scenarios = _build_scenarios(db, sim.plan_id, user.organization_id)
    projections = _build_projections(db, total)

    xlsx = build_workbook(sim_data, scenarios, projections)
    filename = f"presupuesto_sim_{simulation_id}.xlsx"
    return Response(
        content=xlsx,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
