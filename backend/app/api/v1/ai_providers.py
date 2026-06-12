import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/ai-providers", tags=["ai_providers"])

class ProviderModelsRequest(BaseModel):
    provider: str
    api_key: str | None = None

class ModelInfo(BaseModel):
    id: str
    name: str

@router.post("/list-models", response_model=list[ModelInfo])
def list_provider_models(
    payload: ProviderModelsRequest,
    _: User = Depends(get_current_user),
):
    provider = payload.provider.lower()
    
    if provider == "scalist":
        return [ModelInfo(id="scalist-v10", name="Scalist Native (v10)")]
        
    if provider == "gemini":
        try:
            import google.generativeai as genai
            if not payload.api_key:
                raise HTTPException(status_code=400, detail="Falta API Key para Gemini")
            genai.configure(api_key=payload.api_key)
            models = genai.list_models()
            # Filter only models that support vision / generation
            result = []
            for m in models:
                if 'generateContent' in m.supported_generation_methods:
                    result.append(ModelInfo(id=m.name.replace("models/", ""), name=m.display_name or m.name))
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error validando Gemini API Key: {str(e)}")

    if provider == "anthropic":
        return [
            ModelInfo(id="claude-3-5-sonnet-latest", name="Claude 3.5 Sonnet"),
            ModelInfo(id="claude-3-opus-latest", name="Claude 3 Opus"),
            ModelInfo(id="claude-3-haiku-20240307", name="Claude 3 Haiku"),
        ]

    if provider == "openai":
        return [
            ModelInfo(id="gpt-4o", name="GPT-4o"),
            ModelInfo(id="gpt-4-turbo", name="GPT-4 Turbo"),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini"),
        ]

    raise HTTPException(status_code=400, detail="Proveedor no soportado")
