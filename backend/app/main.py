import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from app.core.auth_security import validate_jwt_secret_on_startup

    validate_jwt_secret_on_startup()

    # Health-check de dependencias externas: avisar a ops ANTES de que un
    # usuario pegue contra el error. Ninguna es fatal (el resto de la app anda).
    for binary, feature in [
        ("ODAFileConverter", "import de archivos DWG"),
        ("xvfb-run", "conversión DWG headless"),
    ]:
        if not shutil.which(binary):
            logger.warning(
                "startup: %s no está instalado — %s deshabilitado "
                "(los DXF/PDF/IFC no se ven afectados)", binary, feature,
            )
    yield


app = FastAPI(title="Scalist API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
