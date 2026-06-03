from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assemblies,
    auth,
    integrations,
    materials,
    plans,
    projects,
    team,
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
