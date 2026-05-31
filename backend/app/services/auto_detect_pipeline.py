"""Pipeline de deteccion automatica que corre en background despues de subir
un PDF. Detecta muros, recintos y aberturas en las paginas recomendadas y los
persiste como DetectedElement con source="ai". El editor los muestra con borde
punteado hasta que el usuario los confirma.

El estado del pipeline se trackea en memoria (proceso del backend). Si el
container reinicia, las tareas en vuelo se pierden y el usuario puede
disparar la deteccion manual desde el editor.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Literal

from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement
from app.models.plan import Plan
from app.services.ml_detector import get_ml_detector
from app.services.pdf import recommend_pages

logger = logging.getLogger(__name__)

Stage = Literal[
    "scales", "walls", "rooms", "openings", "columns", "beams", "roofs", "ml"
]
Status = Literal["pending", "running", "done", "failed"]

_progress_lock = threading.Lock()
# { plan_id: { "scales": "done", "walls": "running", ..., "started_at": <ts> } }
_progress: dict[int, dict[str, Any]] = {}


def _init_progress(plan_id: int) -> None:
    with _progress_lock:
        _progress[plan_id] = {
            "scales": "done",  # detect_scales ya corre en upload_plan
            "walls": "pending",
            "rooms": "pending",
            "openings": "pending",
            "columns": "pending",
            "beams": "pending",
            "roofs": "pending",
            "ml": "pending",
            "started_at": time.time(),
        }


def _mark(plan_id: int, stage: Stage, status: Status) -> None:
    with _progress_lock:
        if plan_id in _progress:
            _progress[plan_id][stage] = status


def get_ai_status(plan_id: int) -> dict[str, Any]:
    """Devuelve el progreso del pipeline para un plan. Si no hay registro en
    memoria, devuelve un default que indica "no corrio" — el frontend puede
    decidir si dispara manualmente o no.
    """
    with _progress_lock:
        snapshot = _progress.get(plan_id)
    if snapshot is None:
        return {
            "scales": "pending",
            "walls": "pending",
            "rooms": "pending",
            "openings": "pending",
            "columns": "pending",
            "beams": "pending",
            "roofs": "pending",
            "ml": "pending",
            "started_at": None,
        }
    return dict(snapshot)


def _create_wall_elements(
    db, plan_id: int, page: int, candidates: list[dict], source: str = "ai"
) -> int:
    """Crea DetectedElement(type='wall') a partir de los candidatos.

    `source` puede ser:
      - "ai": detector clásico de OpenCV (default, backwards compat)
      - "ai_ml": detector ML (CubiCasa5K)
      - "manual": dibujado por el usuario
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
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip wall candidate: %s", exc)
    return created


def _create_room_elements(
    db, plan_id: int, page: int, candidates: list[dict], source: str = "ai"
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
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip room candidate: %s", exc)
    return created


def _create_opening_elements(
    db, plan_id: int, page: int, candidates: list[dict], px_per_m: float | None,
    source: str = "ai",
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
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip %s candidate: %s", type_, exc)
    return created


def _create_column_elements(db, plan_id, page, candidates, source: str = "ai") -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "column", 2.8, source
    )


def _create_beam_elements(db, plan_id, page, candidates, source: str = "ai") -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "beam", 0.40, source
    )


def _create_roof_elements(db, plan_id, page, candidates, source: str = "ai") -> int:
    return _create_structural_elements(
        db, plan_id, page, candidates, "roof", 0.20, source
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

    # --- Detección 100% ML ---
    # Una sola etapa de inferencia detecta TODOS los tipos (walls/rooms/openings/
    # beams/columns/roofs). Los detectores clásicos de OpenCV quedaron deprecados:
    # generaban falsos positivos (líneas que no eran muros). El ML detecta con
    # alta precisión lo que está seguro; el resto lo dibuja el usuario a mano.
    # Si el modelo no está disponible, no se crea nada (detección 100% manual).
    await asyncio.to_thread(
        _run_ml_stage,
        plan_id, page_roles, pdf_path, dpi, page_scales, deleted_pages,
    )


_TYPE_STAGES: list[Stage] = [
    "walls", "rooms", "openings", "columns", "beams", "roofs",
]


def _run_ml_stage(
    plan_id: int,
    page_roles: dict[str, list[str]],
    pdf_path: Path,
    dpi: int,
    page_scales: dict,
    deleted_pages: set[int],
) -> None:
    """Corre el detector ML (modelo propio) sobre las páginas asignadas y crea
    los DetectedElement con `source="ai_ml"`. Es la ÚNICA etapa de detección.

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

        # Set de páginas únicas que tienen algún rol asignado.
        pages_to_process: dict[int, set[str]] = {}
        for page_str, roles in page_roles.items():
            try:
                p = int(page_str)
            except (TypeError, ValueError):
                continue
            if p in deleted_pages:
                continue
            pages_to_process[p] = set(roles)

        if not pages_to_process:
            for st in _TYPE_STAGES:
                _mark(plan_id, st, "done")
            _mark(plan_id, "ml", "done")
            return

        total_walls = total_rooms = total_openings = 0
        total_beams = total_columns = total_roofs = 0

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
                    if "walls" in roles:
                        total_walls += _create_wall_elements(
                            db, plan_id, page, result.walls, source="ai_ml"
                        )
                    if "rooms" in roles:
                        total_rooms += _create_room_elements(
                            db, plan_id, page, result.rooms, source="ai_ml"
                        )
                    if "openings" in roles:
                        total_openings += _create_opening_elements(
                            db, plan_id, page, result.openings, px_per_m, source="ai_ml"
                        )
                    if "beams" in roles:
                        total_beams += _create_beam_elements(
                            db, plan_id, page, result.beams, source="ai_ml"
                        )
                    if "columns" in roles:
                        total_columns += _create_column_elements(
                            db, plan_id, page, result.columns, source="ai_ml"
                        )
                    if "roofs" in roles:
                        total_roofs += _create_roof_elements(
                            db, plan_id, page, result.roofs, source="ai_ml"
                        )
            finally:
                doc.close()
            db.commit()

        logger.info(
            "ml stage done plan=%s walls=%d rooms=%d openings=%d "
            "beams=%d columns=%d roofs=%d",
            plan_id, total_walls, total_rooms, total_openings,
            total_beams, total_columns, total_roofs,
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
