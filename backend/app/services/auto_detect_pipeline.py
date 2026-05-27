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
from app.services.opening_detection import detect_opening_labels
from app.services.pdf import recommend_pages
from app.services.wall_room_detection import detect_rooms, detect_walls

logger = logging.getLogger(__name__)

Stage = Literal["scales", "walls", "rooms", "openings"]
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
            "started_at": None,
        }
    return dict(snapshot)


def _create_wall_elements(db, plan_id: int, page: int, candidates: list[dict]) -> int:
    """Crea DetectedElement(type='wall', source='ai') a partir de los candidatos."""
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
                    source="ai",
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip wall candidate: %s", exc)
    return created


def _create_room_elements(db, plan_id: int, page: int, candidates: list[dict]) -> int:
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
                    source="ai",
                )
            )
            created += 1
        except (TypeError, ValueError) as exc:
            logger.warning("skip room candidate: %s", exc)
    return created


def _create_opening_elements(
    db, plan_id: int, page: int, candidates: list[dict], px_per_m: float | None
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
                    source="ai",
                )
            )
            created += 1
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skip opening candidate: %s", exc)
    return created


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


def _process_stage(
    plan_id: int,
    stage: Stage,
    pages: list[int],
    pdf_path: Path,
    dpi: int,
    page_scales: dict,
    detector,
    creator,
    pass_px_per_m: bool = False,
) -> None:
    _mark(plan_id, stage, "running")
    total_created = 0
    try:
        with SessionLocal() as db:
            for page in pages:
                px_per_m = page_scales.get(str(page))
                try:
                    candidates = detector(pdf_path, page - 1, dpi, px_per_m)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("detect %s failed page=%s: %s", stage, page, exc)
                    continue
                if pass_px_per_m:
                    total_created += creator(db, plan_id, page, candidates, px_per_m)
                else:
                    total_created += creator(db, plan_id, page, candidates)
            db.commit()
        _mark(plan_id, stage, "done")
        logger.info("ai %s done plan=%s created=%s", stage, plan_id, total_created)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai %s failed plan=%s: %s", stage, plan_id, exc)
        _mark(plan_id, stage, "failed")


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

    wall_pages = _filter(_pages_for_role(page_roles, "walls"))
    room_pages = _filter(_pages_for_role(page_roles, "rooms"))
    opening_pages = _filter(_pages_for_role(page_roles, "openings"))
    logger.info(
        "ai pipeline start plan=%s walls=%s rooms=%s openings=%s",
        plan_id, wall_pages, room_pages, opening_pages,
    )

    # Cada stage corre en un thread (CPU-bound). Si una etapa no tiene páginas
    # asignadas la marcamos como "done" para que el polling del frontend no
    # quede esperando indefinidamente.
    if wall_pages:
        await asyncio.to_thread(
            _process_stage,
            plan_id, "walls", wall_pages, pdf_path, dpi, page_scales,
            detect_walls, _create_wall_elements, False,
        )
    else:
        _mark(plan_id, "walls", "done")

    if room_pages:
        await asyncio.to_thread(
            _process_stage,
            plan_id, "rooms", room_pages, pdf_path, dpi, page_scales,
            detect_rooms, _create_room_elements, False,
        )
    else:
        _mark(plan_id, "rooms", "done")

    if opening_pages:
        await asyncio.to_thread(
            _process_stage,
            plan_id, "openings", opening_pages, pdf_path, dpi, page_scales,
            detect_opening_labels, _create_opening_elements, True,
        )
    else:
        _mark(plan_id, "openings", "done")
