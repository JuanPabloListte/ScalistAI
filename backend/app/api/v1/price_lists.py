from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.deps import get_current_user
from app.models.user import User
from app.services.price_list_parse import parse_price_list

router = APIRouter(prefix="/price-lists", tags=["price-lists"])

MAX_PRICE_LIST_BYTES = 15 * 1024 * 1024


@router.post("/parse")
async def parse_price_list_preview(
    file: UploadFile = File(...),
    # "true"/"false" fuerza la base de IVA; vacío = detectar.
    iva_included: bool | None = Form(default=None),
    _: User = Depends(get_current_user),
) -> dict:
    """Previsualiza los renglones de un presupuesto de proveedor (PDF/Excel/CSV).
    No persiste nada."""
    data = await file.read()
    if len(data) > MAX_PRICE_LIST_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera los 15 MB.")
    try:
        return parse_price_list(file.filename or "", data, iva_included=iva_included)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
