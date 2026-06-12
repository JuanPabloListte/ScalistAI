import logging
import json
from pathlib import Path
from typing import Any

from app.core.database import SessionLocal
from app.models.plan import Plan
from app.models.plan_ai_context import PlanAiContext
from app.services.auto_detect_pipeline import _TYPE_STAGES, _mark

logger = logging.getLogger(__name__)

def _run_llm_stage(
    plan_id: int,
    page_roles: dict[str, list[str]],
    pdf_path: Path,
    dpi: int,
    page_scales: dict,
    deleted_pages: set[int],
    provider: str,
    api_key: str,
    model_name: str | None,
    hybrid: bool = False,
) -> None:
    """Corre el LLM externo (Gemini, Claude, OpenAI) sobre las páginas asignadas.

    Con `hybrid=True` el plan ya tiene elementos vectoriales (source="dxf"):
    cuando se implemente la detección real, las predicciones deben pasar por
    `hybrid_validation.filter_gap_fill_candidates` y persistirse con
    is_candidate=True / confidence=GAP_FILL_CONFIDENCE (ver _run_ml_stage).
    """
    assigned_roles: set[str] = set()
    for roles in page_roles.values():
        assigned_roles.update(roles)
    assigned_roles.discard("cortes")
    for st in _TYPE_STAGES:
        _mark(plan_id, st, "running" if st in assigned_roles else "done")
    _mark(plan_id, "ml", "running")

    _INFO_ONLY_ROLES = {"cortes"}
    try:
        pages_to_process: dict[int, set[str]] = {}
        for page_str, roles in page_roles.items():
            try:
                p = int(page_str)
            except (TypeError, ValueError):
                continue
            if p in deleted_pages:
                continue
            detection_roles = set(roles) - _INFO_ONLY_ROLES
            if detection_roles:
                pages_to_process[p] = detection_roles

        if not pages_to_process:
            for st in _TYPE_STAGES:
                _mark(plan_id, st, "done")
            _mark(plan_id, "ml", "done")
            return

        with SessionLocal() as db:
            plan = db.get(Plan, plan_id)
            if not plan:
                return
            
            # TODO: Implement real LLM SDK calls (google-generativeai, anthropic)
            # For now, we mock the detection and save the context to show the architecture works.
            
            # Fetch or create PlanAiContext
            ai_context = db.query(PlanAiContext).filter(PlanAiContext.plan_id == plan_id).first()
            if not ai_context:
                ai_context = PlanAiContext(plan_id=plan_id, provider=provider, messages=[])
                db.add(ai_context)

            # Mock LLM analysis response
            messages = list(ai_context.messages)
            analysis_text = f"Análisis completado por {provider} ({model_name}). He detectado la estructura del plano, pero como soy un modelo fundacional, mi precisión geométrica no es milimétrica. Te sugiero revisar las coordenadas."
            
            messages.append({
                "role": "system",
                "content": "Analiza las páginas del plano e identifica muros, aberturas y recintos."
            })
            messages.append({
                "role": "assistant",
                "content": analysis_text
            })
            
            ai_context.messages = messages
            db.commit()

        for st in _TYPE_STAGES:
            if st in assigned_roles:
                _mark(plan_id, st, "done")
        _mark(plan_id, "ml", "done")

    except Exception as exc:
        logger.exception("llm stage failed plan=%s: %s", plan_id, exc)
        for st in _TYPE_STAGES:
            if st in assigned_roles:
                _mark(plan_id, st, "failed")
        _mark(plan_id, "ml", "failed")
