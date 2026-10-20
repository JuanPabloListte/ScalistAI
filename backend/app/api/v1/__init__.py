from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assemblies,
    auth,
    cost_intelligence,
    labor_rates,
    materials,
    plans,
    price_lists,
    rule_sets,
    projects,
    team,
    work_plans,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(plans.router)
api_router.include_router(materials.router, prefix="/materials")
api_router.include_router(assemblies.router, prefix="/assemblies")
api_router.include_router(admin.router)
api_router.include_router(team.router)
api_router.include_router(cost_intelligence.router)
api_router.include_router(work_plans.router)
api_router.include_router(price_lists.router)
api_router.include_router(price_lists.project_router)
api_router.include_router(rule_sets.router)
api_router.include_router(labor_rates.router)
