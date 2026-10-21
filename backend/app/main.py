import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)

# Nombres legibles de los campos que el usuario edita a mano (fallback: el
# nombre crudo del campo).
_FIELD_LABELS = {
    "waste_pct": "Desperdicio",
    "factor": "Cantidad",
    "unit_price": "Precio",
    "name": "Nombre",
    "label": "Nombre",
    "description": "Descripción",
    "keywords": "Palabras a buscar",
    "exclude_keywords": "Palabras a excluir",
    "measure": "Medida",
    "unit": "Unidad",
    "mode": "Modo",
    "daily_yield": "Rendimiento diario",
    "count": "Cantidad",
    "trade": "Oficio",
    "amount": "Cantidad",
    "overhead_pct": "Gastos generales",
    "profit_pct": "Beneficio",
    "email": "Email",
    "password": "Contraseña",
    "file": "Archivo",
    "body": "Los datos enviados",
}
# Listas cuyos elementos conviene numerar ("Regla 3: Desperdicio ...").
_LIST_LABELS = {"rules": "Regla", "crew": "Integrante de la cuadrilla"}


def _num(v) -> str:
    return f"{v:g}".replace(".", ",") if isinstance(v, (int, float)) else str(v)


def _validation_message(err: dict) -> str:
    """Un error de Pydantic/FastAPI en castellano: «Campo: problema»."""
    loc = list(err.get("loc", ()))
    if len(loc) > 1 and loc[0] in ("body", "query", "path", "header", "cookie"):
        loc = loc[1:]  # de dónde vino el dato no le dice nada al usuario
    prefix = ""
    for i, part in enumerate(loc):
        if isinstance(part, int) and i > 0 and loc[i - 1] in _LIST_LABELS:
            prefix = f"{_LIST_LABELS[loc[i - 1]]} {part + 1}: "
    field_name = next((str(p) for p in reversed(loc) if not isinstance(p, int)), "")
    field = _FIELD_LABELS.get(field_name, field_name) or "Dato"
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    if t == "value_error":
        # Validadores propios: su mensaje ya está en castellano.
        msg = str(ctx.get("error") or err.get("msg", "")).removeprefix("Value error, ")
        return f"{prefix}{msg}"
    bounds = {
        "greater_than_equal": ("tiene que ser mayor o igual a", "ge"),
        "greater_than": ("tiene que ser mayor a", "gt"),
        "less_than_equal": ("tiene que ser menor o igual a", "le"),
        "less_than": ("tiene que ser menor a", "lt"),
    }
    if t in bounds:
        text, key = bounds[t]
        problem = f"{text} {_num(ctx.get(key))}"
    elif t == "missing":
        if field_name == "body":
            return "Faltan los datos de la solicitud."
        problem = "es obligatorio"
    elif t in ("float_parsing", "int_parsing", "float_type", "int_type", "int_from_float"):
        problem = "tiene que ser un número"
    elif t == "string_too_long":
        problem = f"puede tener hasta {ctx.get('max_length')} caracteres"
    elif t == "string_too_short":
        problem = ("no puede quedar vacío" if ctx.get("min_length") == 1
                   else f"tiene que tener al menos {ctx.get('min_length')} caracteres")
    elif t in ("string_type", "string_unicode"):
        problem = "tiene que ser un texto"
    elif t in ("bool_parsing", "bool_type"):
        problem = "tiene que ser sí o no"
    elif t == "literal_error":
        problem = f"tiene que ser uno de: {ctx.get('expected')}"
    elif t in ("list_type", "dict_type", "model_type", "model_attributes_type"):
        problem = "tiene un formato inválido"
    elif t == "json_invalid":
        return "Los datos enviados no son un JSON válido."
    else:
        return f"{prefix}{field}: dato inválido"
    return f"{prefix}{field} {problem}"


def validation_detail(errors: list[dict]) -> str:
    msgs: list[str] = []
    for e in errors:
        m = _validation_message(e)
        if m not in msgs:
            msgs.append(m)
    return "; ".join(msgs) or "Datos inválidos."


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from app.core.auth_security import validate_jwt_secret_on_startup

    validate_jwt_secret_on_startup()
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


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 con `detail` en castellano (un string), no la lista cruda de Pydantic
    ("body.rules.0.waste_pct: Input should be..."). El frontend muestra `detail`."""
    return JSONResponse(status_code=422, content={"detail": validation_detail(exc.errors())})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
