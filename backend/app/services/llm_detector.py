import logging
import json
import base64
import math
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from app.core.database import SessionLocal
from app.models.plan import Plan
from app.models.plan_ai_context import PlanAiContext
from app.models.detected_element import DetectedElement
from app.services.auto_detect_pipeline import _TYPE_STAGES, _mark, _vector_elements_for
from app.services.hybrid_validation import (
    GAP_FILL_CONFIDENCE,
    filter_gap_fill_candidates,
)

# Lado mayor de la imagen que se manda al LLM. Anthropic rechaza >8000px /
# ~5MB base64; OpenAI y Gemini tienen límites similares. 2000px alcanza para
# que el modelo distinga muros sin acercarse a esos topes.
_LLM_IMG_MAX_PX = 2000

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert architectural AI assistant.
Your task is to analyze the floor plan image and detect walls.
Identify walls as straight lines. Return ONLY a valid JSON object in the following format:
{
  "walls": [
    [x1, y1, x2, y2],
    ...
  ]
}
The coordinates (x1, y1, x2, y2) must be floats between 0.0 and 1.0, representing the relative position from the top-left corner of the image (0.0 is left/top, 1.0 is right/bottom). Do not include any text outside the JSON.
"""

def _call_openai(api_key: str, model_name: str, base64_image: str) -> str:
    import openai
    client = openai.Client(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name or "gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
            ]}
        ],
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content or "{}"

def _call_anthropic(api_key: str, model_name: str, base64_image: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_name or "claude-opus-4-8",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}},
                {"type": "text", "text": "Extract the walls as JSON."}
            ]}
        ]
    )
    return response.content[0].text

def _call_gemini(api_key: str, model_name: str, base64_image: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name or "gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
    image_part = {
        "mime_type": "image/png",
        "data": base64_image
    }
    response = model.generate_content([image_part, "Extract the walls as JSON."])
    return response.text

def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return {}

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
    """Corre el LLM externo (Gemini, Claude, OpenAI) sobre las páginas asignadas."""
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
            
            ai_context = db.query(PlanAiContext).filter(PlanAiContext.plan_id == plan_id).first()
            if not ai_context:
                ai_context = PlanAiContext(plan_id=plan_id, provider=provider, messages=[])
                db.add(ai_context)

            messages = list(ai_context.messages)
            doc = fitz.open(pdf_path)
            total_walls_detected = 0

            for p, roles in pages_to_process.items():
                if "walls" not in roles:
                    continue
                
                page_obj = doc[p - 1]
                # Zoom calculado para que el lado mayor quede en ~_LLM_IMG_MAX_PX:
                # un zoom fijo sobre una lámina A0 supera los límites de tamaño
                # de imagen de los proveedores (Anthropic: 8000px / 5MB base64).
                long_side_pt = max(page_obj.rect.width, page_obj.rect.height, 1.0)
                zoom = min(2.0, _LLM_IMG_MAX_PX / long_side_pt)
                pix = page_obj.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                base64_image = base64.b64encode(pix.tobytes("png")).decode("utf-8")

                try:
                    if provider == "openai":
                        result_text = _call_openai(api_key, model_name, base64_image)
                    elif provider == "anthropic":
                        result_text = _call_anthropic(api_key, model_name, base64_image)
                    elif provider == "gemini":
                        result_text = _call_gemini(api_key, model_name, base64_image)
                    else:
                        continue

                    data = _extract_json(result_text)
                    walls = data.get("walls", [])

                    # Coords relativas 0-1 → píxeles del raster (dpi del plan),
                    # el mismo espacio en que viven todos los DetectedElement.
                    scale_w = (page_obj.rect.width * dpi) / 72.0
                    scale_h = (page_obj.rect.height * dpi) / 72.0
                    px_per_m = page_scales.get(str(p))

                    candidates: list[dict] = []
                    for w in walls:
                        if not (isinstance(w, (list, tuple)) and len(w) == 4):
                            continue
                        try:
                            x1, y1, x2, y2 = (float(v) for v in w)
                        except (TypeError, ValueError):
                            continue
                        real_pts = [x1 * scale_w, y1 * scale_h, x2 * scale_w, y2 * scale_h]
                        length_m = None
                        if px_per_m:
                            length_m = round(
                                math.hypot(real_pts[2] - real_pts[0], real_pts[3] - real_pts[1])
                                / float(px_per_m), 3,
                            )
                        candidates.append({
                            "geometry": {"points": [round(v, 2) for v in real_pts]},
                            "length_m": length_m,
                        })

                    # Modo híbrido: descartar lo que duplica muros vectoriales
                    # del CAD; solo el gap-fill se propone como candidato.
                    if hybrid and candidates:
                        vec = _vector_elements_for(db, plan_id, p, "wall")
                        candidates = filter_gap_fill_candidates(
                            vec, candidates, "wall", px_per_m,
                            int(scale_w), int(scale_h),
                        )

                    for c in candidates:
                        db.add(DetectedElement(
                            plan_id=plan_id,
                            page=p,
                            type="wall",
                            geometry=c["geometry"],
                            length_m=c["length_m"],
                            height_m=2.8,
                            source="llm",
                            is_candidate=True,
                            confidence=GAP_FILL_CONFIDENCE,
                        ))
                        total_walls_detected += 1
                except Exception as ex:
                    logger.error("Error calling %s for page %s: %s", provider, p, ex)

            doc.close()

            analysis_text = f"Análisis completado por {provider} ({model_name}). He detectado la estructura del plano y extraído {total_walls_detected} muros. Como soy un modelo fundacional, mi precisión geométrica no es milimétrica. Te sugiero revisar las coordenadas y conectar los puntos."
            
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
