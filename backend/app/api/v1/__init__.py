from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assemblies,
    auth,
    cost_intelligence,
    integrations,
    materials,
    plans,
    projects,
    team,
    organization,
    ai_providers,
    work_plans,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(plans.router)
api_router.include_router(materials.router, prefix="/materials")
api_router.include_router(assemblies.router, prefix="/assemblies")
api_router.include_router(integrations.router)
api_router.include_router(admin.router)
api_router.include_router(team.router)
api_router.include_router(organization.router)
api_router.include_router(ai_providers.router)
api_router.include_router(cost_intelligence.router)
api_router.include_router(work_plans.router)
