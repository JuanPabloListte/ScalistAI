from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import require_org_admin
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/organization", tags=["organization"])

class AiConfigRead(BaseModel):
    ai_provider: str
    ai_model_name: str | None
    has_api_key: bool

class AiConfigUpdate(BaseModel):
    ai_provider: str | None = None
    ai_api_key: str | None = None
    ai_model_name: str | None = None

@router.get("/ai-config", response_model=AiConfigRead)
def get_ai_config(
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> AiConfigRead:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    
    org = db.get(Organization, actor.organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")

    return AiConfigRead(
        ai_provider=org.ai_provider,
        ai_model_name=org.ai_model_name,
        has_api_key=bool(org.ai_api_key)
    )

@router.patch("/ai-config", response_model=AiConfigRead)
def update_ai_config(
    payload: AiConfigUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_org_admin),
) -> AiConfigRead:
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    
    org = db.get(Organization, actor.organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")

    if payload.ai_provider is not None:
        org.ai_provider = payload.ai_provider
    if payload.ai_api_key is not None:
        # If empty string, consider it as removal
        org.ai_api_key = payload.ai_api_key if payload.ai_api_key.strip() else None
    if payload.ai_model_name is not None:
        org.ai_model_name = payload.ai_model_name if payload.ai_model_name.strip() else None

    db.commit()
    db.refresh(org)

    return AiConfigRead(
        ai_provider=org.ai_provider,
        ai_model_name=org.ai_model_name,
        has_api_key=bool(org.ai_api_key)
    )
