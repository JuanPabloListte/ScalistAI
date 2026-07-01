"""Pipeline de deteccion automatica que corre en background despues de subir
un PDF. Detecta muros, recintos y aberturas en las paginas asignadas y los
persiste como DetectedElement con source="ai_ml".

El estado del pipeline se persiste en Redis para ser consistente entre los
múltiples workers de Gunicorn en producción. Si Redis no está disponible se
usa un fallback en memoria con el comportamiento original (estado no compartido
entre workers, aceptable en desarrollo).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Literal

from app.core.database import SessionLocal
from app.core.redis import get_redis
from app.models.detected_element import DetectedElement
from app.models.plan import Plan
from app.services.hybrid_validation import (
    GAP_FILL_CONFIDENCE,
    filter_gap_fill_candidates,
    filter_gap_fill_openings,
)
from app.services.ml_detector import get_ml_detector
from app.services.pdf import recommend_pages

logger = logging.getLogger(__name__)

Stage = Literal[
    "scales", "walls", "rooms", "openings", "columns", "beams", "roofs",
    "riostras", "cloacas", "electricidad", "escaleras", "ml",
]
Status = Literal["pending", "running", "done", "failed"]

# TTL del estado en Redis: 2 horas. Suficiente para que cualquier detección
# termine y el frontend termine de polear, sin acumular entradas para siempre.
_STATUS_TTL = 7_200
_KEY_PREFIX = "scalistai:ai:"

# Fallback en memoria para cuando Redis no está disponible.
_mem_lock = threading.Lock()
_mem: dict[int, dict[str, Any]] = {}


def _redis_key(plan_id: int) -> str:
    return f"{_KEY_PREFIX}{plan_id}"


def _default_status() -> dict[str, Any]:
    return {
        "scales": "pending",
        "walls": "pending",
        "rooms": "pending",
        "openings": "pending",
        "columns": "pending",
        "beams": "pending",
        "roofs": "pending",
        "riostras": "pending",
        "cloacas": "pending",
        "electricidad": "pending",
        "escaleras": "pending",
        "ml": "pending",
        "started_at": None,
    }


def _init_progress(plan_id: int) -> None:
    state = {
        **_default_status(),
        "scales": "done",   # detect_scales ya corre en upload_plan
        "started_at": time.time(),
    }
    r = get_redis()
    if r is not None:
        try:
            r.set(_redis_key(plan_id), json.dumps(state), ex=_STATUS_TTL)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis set failed plan=%s: %s — usando fallback", plan_id, exc)
    with _mem_lock:
        _mem[plan_id] = state


def _mark(plan_id: int, stage: str, status: Status) -> None:
    r = get_redis()
    if r is not None:
        try:
            key = _redis_key(plan_id)
            raw = r.get(key)
            state = json.loads(raw) if raw else _default_status()
            state[stage] = status
            r.set(key, json.dumps(state), ex=_STATUS_TTL)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis mark failed plan=%s stage=%s: %s", plan_id, stage, exc)
    with _mem_lock:
        if plan_id in _mem:
            _mem[plan_id][stage] = status


def get_ai_status(plan_id: int) -> dict[str, Any]:
    """Devuelve el progreso del pipeline para un plan.

    Lee de Redis (compartido entre todos los workers). Si Redis no está
    disponible cae al fallback en memoria con comportamiento original.
    """
    r = get_redis()
    if r is not None:
        try:
            raw = r.get(_redis_key(plan_id))
            if raw:
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis get failed plan=%s: %s", plan_id, exc)
    with _mem_lock:
        snapshot = _mem.get(plan_id)
    return dict(snapshot) if snapshot else _default_status()


def _create_wall_elements(
    db, plan_id: int, page: int, candidates: list[dict], source: str = "ai",
    is_candidate: bool = False, confidence: float = 1.0,
) -> int:
    """Crea DetectedElement(type='wall') a partir de los candidatos.

    `source` puede ser:
      - "ai": detector clásico de OpenCV (default, backwards compat)
      - "ai_ml": detector ML (CubiCasa5K)
      - "manual": dibujado por el usuario

    `is_candidate=True` marca propuestas pendientes de aprobación (modo
    híbrido: la IA propone, el usuario acepta).
    """
    created = 0
    for c in candidates:
        try:
            geometry = c.get("geometry") or {}
            length_m = c.get("length_m")
            if not geometry or length_m is None:
                continue
            db.add(
                DetectedElement(
                    plan_id=plan_id,
                    page=page,
                    type="wall",
                    geometry=geometry,
                    length_m=float(length_m),
                    height_m=2.8,
                    source=source,
                    is_candidate=is_candidate,
                    confidence=confidence,
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip wall candidate: %s", exc)
    return created


def _create_room_elements(
    db, plan_id: int, page: int, candidates: list[dict], source: str = "ai",
    is_candidate: bool = False, confidence: float = 1.0,
) -> int:
    created = 0
    for c in candidates:
        try:
            geometry = c.get("geometry") or {}
            if not geometry:
                continue
            db.add(
                DetectedElement(
                    plan_id=plan_id,
                    page=page,
                    type="room",
                    geometry=geometry,
                    length_m=c.get("length_m"),
                    area_m2=c.get("area_m2"),
                    height_m=2.8,
                    source=source,
                    is_candidate=is_candidate,
                    confidence=confidence,
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip room candidate: %s", exc)
    return created


def _create_opening_elements(
    db, plan_id: int, page: int, candidates: list[dict], px_per_m: float | None,
    source: str = "ai", is_candidate: bool = False, confidence: float = 1.0,
) -> int:
    if not px_per_m:
        return 0
    created = 0
    for c in candidates:
        try:
            cx = float(c["cx"])
            cy = float(c["cy"])
            width_m = float(c.get("default_width_m") or 0.8)
            orientation = str(c.get("orientation") or "h").lower()
            label = str(c.get("label") or "")
            subtype = str(c.get("subtype") or "door")
            half_px = (width_m / 2.0) * px_per_m
            if orientation == "v":
                p1 = (cx, cy - half_px)
                p2 = (cx, cy + half_px)
            else:
                p1 = (cx - half_px, cy)
                p2 = (cx + half_px, cy)
            db.add(
                DetectedElement(
                    plan_id=plan_id,
                    page=page,
                    type="opening",
                    geometry={
                        "points": [p1[0], p1[1], p2[0], p2[1]],
                        "label": label or f"Abertura {created + 1}",
                        "subtype": subtype,
                    },
                    length_m=width_m,
                    height_m=2.1,
                    source=source,
                    is_candidate=is_candidate,
                    confidence=confidence,
                )
            )
            created += 1
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skip opening candidate: %s", exc)
    return created


def _create_structural_elements(
    db,
    plan_id: int,
    page: int,
    candidates: list[dict],
    type_: str,
    default_height_m: float,
    source: str = "ai",
    is_candidate: bool = False,
    confidence: float = 1.0,
) -> int:
    """Persiste candidatos de columnas, vigas o losas como DetectedElement.

    Todos siguen el mismo schema (geometry polígono + length/area/height
    opcionales). El tipo concreto (`column`, `beam`, `roof`) y la altura
    default por defecto los decide el caller, porque cada uno tiene
    semántica distinta (columna = altura piso, viga = peralte, losa =
    espesor).
    """
    created = 0
    for c in candidates:
        try:
            geometry = c.get("geometry") or {}
            if not geometry:
                continue
            db.add(
                DetectedElement(
                    plan_id=plan_id,
                    page=page,
                    type=type_,
                    geometry=geometry,
                    length_m=c.get("length_m"),
                    area_m2=c.get("area_m2"),
                    height_m=c.get("height_m") or default_height_m,
                    source=source,
                    is_candidate=is_candidate,
                    confidence=confidence,
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip %s candidate: %s", type_, exc)
    return created


def _create_column_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "column", 2.8, source, **flags
    )


def _create_beam_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "beam", 0.40, source, **flags
    )


def _create_roof_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "roof", 0.20, source, **flags
    )


def _create_riostra_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "riostra", 0.40, source, **flags
    )


def _create_cloaca_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "cloaca", 0.10, source, **flags
    )


def _create_electricidad_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "electricidad", 0.05, source, **flags
    )


def _create_escalera_elements(db, plan_id, page, candidates, source: str = "ai", **flags) -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "escalera", 2.8, source, **flags
    )


def _recommended_pages(pdf_path: Path) -> list[int]:
    try:
        recs = recommend_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("recommend_pages failed: %s", exc)
        return [1]
    pages = [r["page"] for r in recs if r.get("recommended")]
    # Si nada califica, igual procesamos la primera pagina para no dejar
    # al usuario sin candidatos.
    return pages or [1]


def _pages_for_role(page_roles: dict[str, list[str]], role: str) -> list[int]:
    """Devuelve la lista ordenada de páginas (1-indexed) que tienen el rol dado."""
    pages: list[int] = []
    for page_str, roles in page_roles.items():
        if role in roles:
            try:
                pages.append(int(page_str))
            except (TypeError, ValueError):
                continue
    return sorted(set(pages))


def run_initial_detection_sync(plan_id: int) -> None:
    """Entrada SYNC para el worker de jobs (rq no ejecuta corutinas).
    También sirve como fallback in-process: BackgroundTasks la corre en su
    threadpool, donde no hay event loop y asyncio.run es válido."""
    asyncio.run(run_initial_detection(plan_id))


async def run_initial_detection(plan_id: int) -> None:
    """Punto de entrada del background task. Lee `plan.page_roles` y corre cada
    detector **solo sobre sus páginas asignadas**.

    Esto reemplaza el comportamiento previo de correr los 3 detectores sobre
    las mismas páginas "recomendadas": ahora el usuario decide explícitamente
    en el wizard qué página sirve para muros, cuál para aberturas y cuál para
    recintos. Resultados mucho más limpios.

    Si `page_roles` está vacío o nulo, no se hace nada (el wizard debería
    forzar al usuario a asignar al menos una página).
    """
    _init_progress(plan_id)

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return
        pdf_path = Path(plan.pdf_path)
        if not pdf_path.exists():
            return
        dpi = plan.dpi or 150
        page_scales = dict(plan.page_scales or {})
        deleted_pages = set(plan.deleted_pages or [])
        page_roles = dict(plan.page_roles or {})
        
        # BYOK config
        org = plan.project.organization
        ai_provider = getattr(org, "ai_provider", "scalist")
        ai_api_key = getattr(org, "ai_api_key", None)
        ai_model_name = getattr(org, "ai_model_name", None)

        # Si el import vectorial ya creó elementos exactos desde las capas del
        # PDF (pdf_vector_import), entramos en modo HÍBRIDO: la IA corre igual
        # pero sus predicciones se cruzan contra los elementos vectoriales.
        # Duplicados se descartan (el vector manda); lo que la IA encuentra
        # donde el CAD no tiene nada se guarda como candidato a aprobar.
        hybrid_mode = (
            db.query(DetectedElement)
            .filter(DetectedElement.plan_id == plan_id, DetectedElement.source == "dxf")
            .first()
            is not None
        )

    if hybrid_mode:
        logger.info(
            "ai pipeline hybrid plan=%s: cross-validation contra elementos vectoriales",
            plan_id,
        )

    if not page_roles:
        logger.info("ai pipeline skip plan=%s: sin page_roles asignados", plan_id)
        return

    def _filter(pages: list[int]) -> list[int]:
        return [p for p in pages if p not in deleted_pages]

    logger.info(
        "ai pipeline start (ML-only) plan=%s walls=%s rooms=%s openings=%s "
        "columns=%s beams=%s roofs=%s",
        plan_id,
        _filter(_pages_for_role(page_roles, "walls")),
        _filter(_pages_for_role(page_roles, "rooms")),
        _filter(_pages_for_role(page_roles, "openings")),
        _filter(_pages_for_role(page_roles, "columns")),
        _filter(_pages_for_role(page_roles, "beams")),
        _filter(_pages_for_role(page_roles, "roofs")),
    )

    # --- Detección Híbrida / ML / LLM ---
    # El detector LLM (BYOK) está detrás de un flag y apagado por default:
    # solo detecta muros y su precisión de coordenadas no alcanza para cómputo.
    # Con el flag apagado, una org con api key configurada usa el camino ML.
    from app.core.config import settings as app_settings

    use_llm = (
        app_settings.ENABLE_LLM_DETECTOR
        and ai_provider != "scalist"
        and bool(ai_api_key)
    )
    if not use_llm:
        if ai_provider != "scalist" and ai_api_key:
            logger.info(
                "llm detector deshabilitado por flag (ENABLE_LLM_DETECTOR=False) "
                "plan=%s: se usa el camino ML", plan_id,
            )
        await asyncio.to_thread(
            _run_ml_stage,
            plan_id, page_roles, pdf_path, dpi, page_scales, deleted_pages,
            hybrid_mode,
        )
    else:
        from app.services.llm_detector import _run_llm_stage
        await asyncio.to_thread(
            _run_llm_stage,
            plan_id, page_roles, pdf_path, dpi, page_scales, deleted_pages,
            ai_provider, ai_api_key, ai_model_name, hybrid_mode,
        )


_TYPE_STAGES: list[Stage] = [
    "walls", "rooms", "openings", "columns", "beams", "roofs",
    "riostras", "cloacas", "electricidad", "escaleras",
]


def _vector_elements_for(db, plan_id: int, page: int, el_type: str) -> list:
    """Elementos vectoriales (source='dxf') de un tipo en una página."""
    return (
        db.query(DetectedElement)
        .filter(
            DetectedElement.plan_id == plan_id,
            DetectedElement.page == page,
            DetectedElement.type == el_type,
            DetectedElement.source == "dxf",
        )
        .all()
    )


def _run_ml_stage(
    plan_id: int,
    page_roles: dict[str, list[str]],
    pdf_path: Path,
    dpi: int,
    page_scales: dict,
    deleted_pages: set[int],
    hybrid: bool = False,
) -> None:
    """Corre el detector ML (modelo propio) sobre las páginas asignadas y crea
    los DetectedElement con `source="ai_ml"`. Es la ÚNICA etapa de detección.

    Con `hybrid=True` (el PDF ya aportó elementos vectoriales exactos), las
    predicciones se cruzan contra el CAD: duplicados se descartan y lo nuevo
    se persiste como candidato (is_candidate=True) a aprobar por el usuario.

    Diseño:
      - Una sola inferencia por página: el modelo predice walls/rooms/openings/
        beams/columns/roofs de una sola pasada.
      - Por cada página, sólo se persisten los tipos asignados al rol de esa
        página.
      - Mueve el progreso por tipo (para el banner del frontend) además del
        stage "ml".
      - Si el modelo no está cargado, marca todo como "done" sin crear nada
        (la detección automática queda deshabilitada; el usuario dibuja a mano).
    """
    # Tipos asignados en alguna página → mueven su barra de progreso; el resto
    # se marca "done" de entrada para que el polling no quede esperando.
    assigned_roles: set[str] = set()
    for roles in page_roles.values():
        assigned_roles.update(roles)
    assigned_roles.discard("cortes")
    for st in _TYPE_STAGES:
        _mark(plan_id, st, "running" if st in assigned_roles else "done")

    ml = get_ml_detector()
    if not ml.is_available():
        for st in _TYPE_STAGES:
            _mark(plan_id, st, "done")
        _mark(plan_id, "ml", "done")
        logger.warning(
            "ml stage skip plan=%s: modelo no disponible — sin detección "
            "automática (el usuario dibuja a mano)", plan_id,
        )
        return

    _mark(plan_id, "ml", "running")
    try:
        import fitz
        import numpy as np
        import cv2  # noqa: F401  # usado indirectamente al cargar la imagen

        # Set de páginas únicas que tienen algún rol de detección asignado.
        # Páginas con solo "cortes" (elevaciones/fachadas) se saltan: no
        # generan elementos, son solo referencia visual de alturas.
        _INFO_ONLY_ROLES = {"cortes"}
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

        total_walls = total_rooms = total_openings = 0
        total_beams = total_columns = total_roofs = 0
        total_riostras = total_cloacas = total_electricidad = 0

        with SessionLocal() as db:
            doc = fitz.open(pdf_path)
            try:
                for page, roles in sorted(pages_to_process.items()):
                    if page - 1 < 0 or page - 1 >= doc.page_count:
                        continue
                    px_per_m = page_scales.get(str(page))
                    try:
                        # Renderizar página a RGB uint8
                        p_obj = doc.load_page(page - 1)
                        zoom = dpi / 72.0
                        pixmap = p_obj.get_pixmap(
                            matrix=fitz.Matrix(zoom, zoom), alpha=False
                        )
                        img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                            pixmap.height, pixmap.width, 3
                        )
                        # Inferencia ML
                        result = ml.detect(img, px_per_m, page_index=page - 1)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("ml inference failed page=%s: %s", page, exc)
                        continue

                    # Persistir candidatos por rol asignado a esta página.
                    # En modo híbrido, cada lista pasa por el cross-validation
                    # contra los elementos vectoriales antes de persistirse, y
                    # lo que sobrevive entra como candidato a aprobar.
                    img_h, img_w = pixmap.height, pixmap.width
                    flags: dict = (
                        {"is_candidate": True, "confidence": GAP_FILL_CONFIDENCE}
                        if hybrid else {}
                    )

                    def _gap_fill(el_type: str, candidates: list[dict]) -> list[dict]:
                        if not hybrid:
                            return candidates
                        vec = _vector_elements_for(db, plan_id, page, el_type)
                        return filter_gap_fill_candidates(
                            vec, candidates, el_type, px_per_m, img_w, img_h
                        )

                    if "walls" in roles:
                        total_walls += _create_wall_elements(
                            db, plan_id, page, _gap_fill("wall", result.walls),
                            source="ai_ml", **flags,
                        )
                    if "rooms" in roles:
                        total_rooms += _create_room_elements(
                            db, plan_id, page, _gap_fill("room", result.rooms),
                            source="ai_ml", **flags,
                        )
                    if "openings" in roles:
                        openings = result.openings
                        if hybrid:
                            openings = filter_gap_fill_openings(
                                _vector_elements_for(db, plan_id, page, "opening"),
                                openings, px_per_m,
                            )
                        total_openings += _create_opening_elements(
                            db, plan_id, page, openings, px_per_m,
                            source="ai_ml", **flags,
                        )
                    if "beams" in roles:
                        total_beams += _create_beam_elements(
                            db, plan_id, page, _gap_fill("beam", result.beams),
                            source="ai_ml", **flags,
                        )
                    if "columns" in roles:
                        total_columns += _create_column_elements(
                            db, plan_id, page, _gap_fill("column", result.columns),
                            source="ai_ml", **flags,
                        )
                    if "roofs" in roles:
                        total_roofs += _create_roof_elements(
                            db, plan_id, page, _gap_fill("roof", result.roofs),
                            source="ai_ml", **flags,
                        )
                    if "riostra" in roles or "riostras" in roles:
                        total_riostras += _create_riostra_elements(
                            db, plan_id, page, _gap_fill("riostra", result.riostras),
                            source="ai_ml", **flags,
                        )
                    if "cloaca" in roles or "cloacas" in roles:
                        total_cloacas += _create_cloaca_elements(
                            db, plan_id, page, _gap_fill("cloaca", result.cloacas),
                            source="ai_ml", **flags,
                        )
                    if "electricidad" in roles:
                        total_electricidad += _create_electricidad_elements(
                            db, plan_id, page, _gap_fill("electricidad", result.electricidad),
                            source="ai_ml", **flags,
                        )
                    if "escalera" in roles or "escaleras" in roles:
                        _create_escalera_elements(
                            db, plan_id, page, _gap_fill("escalera", result.escaleras),
                            source="ai_ml", **flags,
                        )
            finally:
                doc.close()
            db.commit()

        logger.info(
            "ml stage done plan=%s walls=%d rooms=%d openings=%d "
            "beams=%d columns=%d roofs=%d riostras=%d cloacas=%d electricidad=%d",
            plan_id, total_walls, total_rooms, total_openings,
            total_beams, total_columns, total_roofs,
            total_riostras, total_cloacas, total_electricidad,
        )
        for st in _TYPE_STAGES:
            if st in assigned_roles:
                _mark(plan_id, st, "done")
        _mark(plan_id, "ml", "done")
    except Exception as exc:  # noqa: BLE001
        logger.exception("ml stage failed plan=%s: %s", plan_id, exc)
        for st in _TYPE_STAGES:
            if st in assigned_roles:
                _mark(plan_id, st, "failed")
        _mark(plan_id, "ml", "failed")
