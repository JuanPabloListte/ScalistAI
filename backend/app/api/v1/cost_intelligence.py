"""Interface (HTTP) del Motor de Inteligencia de Costos — Módulo 2.

Cablea los casos de uso del bounded context (`RunSimulation`,
`CompareScenarios`) con los adapters SQL y la auth/multi-tenancy existente.
"""
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.cost_intelligence.application.use_cases.compare_scenarios import CompareScenarios
from app.cost_intelligence.application.use_cases.forecast_cost import ForecastCost
from app.cost_intelligence.application.use_cases.run_simulation import RunSimulation
from app.cost_intelligence.domain.material_trend import project_material
from app.cost_intelligence.domain.pricing_breakdown import IndirectRates, build_price
from app.cost_intelligence.domain.value_objects import Money
from app.cost_intelligence.infrastructure.export.xlsx_exporter import build_workbook
from app.cost_intelligence.infrastructure.forecasting.deterministic import DeterministicForecaster
from app.cost_intelligence.infrastructure.persistence.cost_settings_repo import SqlCostSettingsRepo
from app.cost_intelligence.infrastructure.persistence.macro_rate_provider import SqlMacroRateProvider
from app.cost_intelligence.infrastructure.persistence.measurement_provider import SqlMeasurementProvider
from app.cost_intelligence.infrastructure.persistence.recipe_catalog import SqlRecipeCatalog
from app.cost_intelligence.infrastructure.persistence.simulation_store import SqlSimulationStore
from app.models import Assembly, ConstructionEntity, Plan, Project, Simulation, User
from app.models.detected_element import DetectedElement
from app.models.material import Material
from app.models.material_group import MaterialGroup
from app.models.price_history import MaterialPriceHistory
from app.schemas.budget_summary import (
    BudgetCategory, BudgetTakeoff, ProjectBudgetSummary, SalePriceBreakdown,
)
from app.schemas.cost_settings import (
    CostSettingsRead, CostSettingsUpdate, ParametricRubro, ParametricRubrosUpdate,
)
from app.schemas.forecast import ForecastRequest, ForecastResponse
from app.schemas.price_series import PriceSeriesPoint, PriceSeriesProduct
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

    # Costo directo -> precio de venta (gastos generales + beneficio + IVA).
    rates = SqlCostSettingsRepo(db).rates(user.organization_id)
    bd = build_price(total, rates)
    breakdown = {
        "overhead": float(bd.overhead.amount), "profit": float(bd.profit.amount),
        "net": float(bd.net.amount), "iva": float(bd.iva.amount), "total": float(bd.total.amount),
    }

    xlsx = build_workbook(sim_data, scenarios, projections, breakdown)
    db.commit()  # persiste los cost_settings default si se crearon recién
    filename = f"presupuesto_sim_{simulation_id}.xlsx"
    return Response(
        content=xlsx,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cost-settings", response_model=CostSettingsRead)
def get_cost_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CostSettingsRead:
    s = SqlCostSettingsRepo(db).get_or_create(user.organization_id)
    db.commit()
    return CostSettingsRead(overhead_pct=s.overhead_pct, profit_pct=s.profit_pct, iva_pct=s.iva_pct)


@router.put("/cost-settings", response_model=CostSettingsRead)
def update_cost_settings(
    payload: CostSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CostSettingsRead:
    s = SqlCostSettingsRepo(db).update(
        user.organization_id,
        overhead_pct=payload.overhead_pct,
        profit_pct=payload.profit_pct,
        iva_pct=payload.iva_pct,
    )
    db.commit()
    return CostSettingsRead(overhead_pct=s.overhead_pct, profit_pct=s.profit_pct, iva_pct=s.iva_pct)


@router.get("/parametric-rubros", response_model=list[ParametricRubro])
def get_parametric_rubros(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ParametricRubro]:
    """Rubros estimados (fundaciones, instalaciones, terminaciones) como % de la
    obra gris. Lo que el modelo IFC/plano no trae. Editable por org."""
    rubros = SqlCostSettingsRepo(db).parametric_rubros(user.organization_id)
    db.commit()
    return [ParametricRubro(**r) for r in rubros]


@router.put("/parametric-rubros", response_model=list[ParametricRubro])
def update_parametric_rubros(
    payload: ParametricRubrosUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ParametricRubro]:
    rubros = SqlCostSettingsRepo(db).update_parametric_rubros(
        user.organization_id, [r.model_dump() for r in payload.rubros])
    db.commit()
    return [ParametricRubro(**r) for r in rubros]


_OPENING_TYPES = ("opening", "door", "window", "sliding_door")


@router.get("/plans/{plan_id}/budget-summary", response_model=ProjectBudgetSummary)
def budget_summary(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectBudgetSummary:
    """Presupuesto COMPLETO del proyecto: total, desglose por rubro y resumen de
    cómputo (ml de muro, aberturas, etc.). Corre la simulación y agrega."""
    _assert_plan_in_org(db, plan_id, user.organization_id)
    plan = db.get(Plan, plan_id)
    project = db.get(Project, plan.project_id)

    scenario = RunSimulation(SqlMeasurementProvider(db), SqlRecipeCatalog(db)).execute(
        plan_id, user.organization_id)
    materials_total = float(scenario.totals.materials.amount)
    labor_total = float(scenario.totals.labor_cost.amount)
    obra_gris = materials_total + labor_total  # costo directo de lo MODELADO

    # Rubros: materiales por categoría + Mano de Obra como rubro propio.
    mat_ids = [ln.material_id for ln in scenario.lines]
    cat_by_id = dict(db.execute(
        select(Material.id, Material.category).where(Material.id.in_(mat_ids))).all()) if mat_ids else {}
    cat_totals: dict[str, float] = defaultdict(float)
    for ln in scenario.lines:
        cat_totals[cat_by_id.get(ln.material_id) or "Otros"] += float(ln.total.amount)
    if labor_total > 0:
        cat_totals["Mano de Obra"] += labor_total

    # Takeoff de cantidades desde los elementos aprobados.
    els = db.scalars(select(DetectedElement).where(
        DetectedElement.plan_id == plan_id,
        DetectedElement.is_candidate.is_(False))).all()

    def _sum(pred, attr):
        return float(sum(getattr(e, attr) or 0 for e in els if pred(e)))

    floor_m2 = _sum(lambda e: e.type == "room", "area_m2")
    roof_m2 = _sum(lambda e: e.type == "roof", "area_m2") or floor_m2
    # Área estimada (huella×pisos) cuando el IFC no trae ambientes reales.
    area_estimated = any(
        (e.geometry or {}).get("subtype") == "estimated_floor"
        for e in els if e.type == "room")
    openings = [e for e in els if e.type in _OPENING_TYPES]
    doors = sum(1 for e in openings if (e.geometry or {}).get("subtype") in ("door", "sliding_door"))
    windows = sum(1 for e in openings if (e.geometry or {}).get("subtype") == "window")
    takeoff = BudgetTakeoff(
        wall_ml=_sum(lambda e: e.type == "wall", "length_m"),
        wall_m2=float(sum((e.length_m or 0) * (e.height_m or 2.8) for e in els if e.type == "wall")),
        openings=len(openings), doors=doors, windows=windows,
        columns=sum(1 for e in els if e.type == "column"),
        beams_ml=_sum(lambda e: e.type == "beam", "length_m"),
        roof_m2=roof_m2,
        cloaca_ml=_sum(lambda e: e.type == "cloaca", "length_m"),
        electricidad_ml=_sum(lambda e: e.type == "electricidad", "length_m"),
        rooms=sum(1 for e in els if e.type == "room"),
        floor_m2=floor_m2,
        sanitarios=sum(1 for e in els if e.type == "sanitario"),
        bocas_electricas=sum(1 for e in els if e.type == "boca_electrica"),
        escaleras=sum(1 for e in els if e.type == "escalera"),
    )

    area = floor_m2
    repo = SqlCostSettingsRepo(db)
    cs = repo.get_or_create(user.organization_id)

    # Rubros PARAMÉTRICOS: lo que el modelo no trae (fundaciones, instalaciones,
    # terminaciones) estimado como % sobre la obra gris. Estimación explícita,
    # editable por org; se marcan como parametric=True para diferenciarlos.
    prubros = repo.parametric_rubros(user.organization_id)
    parametric_cats = [(r["label"], obra_gris * r["pct"])
                       for r in prubros if r.get("pct", 0) > 0]
    parametric_total = float(sum(t for _, t in parametric_cats))
    direct = obra_gris + parametric_total
    db.commit()

    breakdown = build_price(Money(direct), IndirectRates(
        Decimal(str(cs.overhead_pct)), Decimal(str(cs.profit_pct)), Decimal(str(cs.iva_pct))))

    def _cat(name, total, parametric):
        return BudgetCategory(name=name, total=total,
                              pct=(total / direct * 100 if direct else 0.0),
                              per_m2=(total / area if area else None), parametric=parametric)

    modeled = sorted((_cat(k, v, False) for k, v in cat_totals.items()), key=lambda c: -c.total)
    estimated = sorted((_cat(n, t, True) for n, t in parametric_cats), key=lambda c: -c.total)
    categories = modeled + estimated  # primero lo modelado, luego los estimados

    return ProjectBudgetSummary(
        plan_id=plan_id, project_name=project.name, area_m2=area,
        area_estimated=area_estimated,
        materials_total=materials_total, labor_total=labor_total,
        labor_hours=float(scenario.totals.labor_hours),
        duration_days=float(scenario.totals.duration_days),
        obra_gris_direct=obra_gris, parametric_total=parametric_total,
        direct_cost=direct, sale_price=float(breakdown.total.amount),
        cost_per_m2=(direct / area if area else None),
        breakdown=SalePriceBreakdown(
            direct=direct,
            overhead=float(breakdown.overhead.amount),
            profit=float(breakdown.profit.amount),
            iva=float(breakdown.iva.amount),
            total=float(breakdown.total.amount),
        ),
        categories=categories, takeoff=takeoff,
    )


@router.get("/price-series", response_model=list[PriceSeriesProduct])
def price_series(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PriceSeriesProduct]:
    """Serie histórica REAL de precios por producto canónico (MaterialGroup),
    consolidando los PricePoint de todos sus materiales equivalentes. Aislado
    por org. Solo grupos con ≥1 punto."""
    ipc_rate_dec = SqlMacroRateProvider(db).monthly_rate("IPC")
    ipc_rate = float(ipc_rate_dec) if ipc_rate_dec is not None else None
    horizon = 6

    groups = db.scalars(
        select(MaterialGroup)
        .where(MaterialGroup.organization_id == user.organization_id)
        .order_by(MaterialGroup.name)
    ).all()
    out: list[PriceSeriesProduct] = []
    for g in groups:
        member_ids = [m.id for m in g.members]
        if not member_ids:
            continue
        rows = db.execute(
            select(MaterialPriceHistory.date, MaterialPriceHistory.price, MaterialPriceHistory.source)
            .where(MaterialPriceHistory.material_id.in_(member_ids))
            .order_by(MaterialPriceHistory.date)
        ).all()
        if not rows:
            continue
        points = [PriceSeriesPoint(date=d.date(), price=p, source=s.split(" (")[0]) for d, p, s in rows]
        first, last = points[0].price, points[-1].price
        fc = project_material([(p.date, p.price) for p in points], horizon, ipc_rate)
        out.append(PriceSeriesProduct(
            id=g.id, name=g.name, category=g.category, unit=g.unit, points=points,
            first_price=first, last_price=last,
            change_pct=((last / first - 1) * 100 if first else None),
            horizon_months=horizon,
            projected_price=fc.projected_price,
            forecast_rate=fc.monthly_rate,
            forecast_method=fc.method,
            forecast_variation_pct=fc.variation_pct,
            ipc_monthly_rate=fc.ipc_monthly_rate,
            beats_inflation=fc.beats_inflation,
        ))
    return out
