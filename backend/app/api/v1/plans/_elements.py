from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import DetectedElement, Plan, User
from app.schemas.detected_element import (
    CandidateBulkAction,
    DetectedElementCreate,
    DetectedElementRead,
    DetectedElementUpdate,
)

router = APIRouter(tags=["plans"])


@router.post(
    "/plans/{plan_id}/elements",
    response_model=DetectedElementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_element(
    plan_id: int,
    payload: DetectedElementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = DetectedElement(
        plan_id=plan_id,
        page=payload.page,
        type=payload.type,
        geometry=payload.geometry,
        length_m=payload.length_m,
        area_m2=payload.area_m2,
        height_m=payload.height_m,
        source=payload.source,
    )
    db.add(element)
    db.commit()
    db.refresh(element)
    return element


@router.get("/plans/{plan_id}/elements", response_model=list[DetectedElementRead])
def list_elements(
    plan_id: int,
    page: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    stmt = select(DetectedElement).where(DetectedElement.plan_id == plan_id)
    if page is not None:
        stmt = stmt.where(DetectedElement.page == page)
    stmt = stmt.order_by(DetectedElement.created_at.asc())
    return list(db.scalars(stmt).all())


@router.patch("/plans/{plan_id}/elements/{element_id}", response_model=DetectedElementRead)
def update_element(
    plan_id: int,
    element_id: int,
    payload: DetectedElementUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(element, field, value)

    db.commit()
    db.refresh(element)
    return element


@router.delete("/plans/{plan_id}/elements/{element_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_element(
    plan_id: int,
    element_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    db.delete(element)
    db.commit()


@router.post(
    "/plans/{plan_id}/elements/candidates/bulk-action",
    response_model=list[DetectedElementRead],
)
def candidates_bulk_action(
    plan_id: int,
    payload: CandidateBulkAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    """Acepta o descarta propuestas de la IA (is_candidate=True) en lote.

    - accept: el elemento pasa a confirmado (is_candidate=False, confidence=1.0,
      source="ai" = aceptado explícitamente) y empieza a computar.
    - discard: se elimina.

    Devuelve los elementos aceptados (lista vacía para discard).
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    query = db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.is_candidate.is_(True),
    )
    if payload.element_ids is not None:
        if not payload.element_ids:
            return []
        query = query.filter(DetectedElement.id.in_(payload.element_ids))
    if payload.page is not None:
        query = query.filter(DetectedElement.page == payload.page)

    candidates = query.all()
    if not candidates:
        return []

    if payload.action == "accept":
        for el in candidates:
            el.is_candidate = False
            el.confidence = 1.0
            el.source = "ai"
        db.commit()
        for el in candidates:
            db.refresh(el)
        return candidates

    # discard
    ids = [el.id for el in candidates]
    db.query(DetectedElement).filter(DetectedElement.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return []


@router.post("/plans/{plan_id}/elements/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
def bulk_delete_elements(
    plan_id: int,
    payload: list[int],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if not payload:
        return

    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.id.in_(payload),
    ).delete(synchronize_session=False)
    db.commit()


@router.post(
    "/plans/{plan_id}/elements-bulk",
    response_model=list[DetectedElementRead],
    status_code=status.HTTP_201_CREATED,
)
def create_elements_bulk(
    plan_id: int,
    payload: list[dict],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    """Crea N elementos a partir de candidatos aceptados desde el ML."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    created: list[DetectedElement] = []
    for item in payload:
        try:
            page = int(item["page"])
            el_type = str(item["type"])
            geometry = dict(item["geometry"])
            length_m = float(item["length_m"]) if item.get("length_m") is not None else None
            area_m2 = float(item["area_m2"]) if item.get("area_m2") is not None else None
            height_m = float(item.get("height_m") or 2.8)
        except (KeyError, TypeError, ValueError):
            continue

        element = DetectedElement(
            plan_id=plan_id,
            page=page,
            type=el_type,
            geometry=geometry,
            length_m=length_m,
            area_m2=area_m2,
            height_m=height_m,
            source="ai",
        )
        db.add(element)
        created.append(element)

    if created:
        db.commit()
        for el in created:
            db.refresh(el)

    return created


@router.post(
    "/plans/{plan_id}/openings-bulk",
    response_model=list[DetectedElementRead],
    status_code=status.HTTP_201_CREATED,
)
def create_openings_bulk(
    plan_id: int,
    payload: list[dict],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    """Crea N aberturas a partir de candidatos ML con posicionamiento por px_per_m."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    scales = plan.page_scales or {}
    created: list[DetectedElement] = []
    existing_count_per_page: dict[int, int] = {}

    for item in payload:
        try:
            page = int(item["page"])
            cx = float(item["cx"])
            cy = float(item["cy"])
            width_m = float(item.get("default_width_m") or 0.8)
            label = str(item.get("label") or "")
            subtype = str(item.get("subtype") or "door")
        except (KeyError, TypeError, ValueError):
            continue

        px_per_m = scales.get(str(page))
        if not px_per_m:
            continue

        orientation = str(item.get("orientation") or "h").lower()
        half_px = (width_m / 2.0) * px_per_m
        if orientation == "v":
            p1 = (cx, cy - half_px)
            p2 = (cx, cy + half_px)
        else:
            p1 = (cx - half_px, cy)
            p2 = (cx + half_px, cy)

        if page not in existing_count_per_page:
            existing_count_per_page[page] = (
                db.query(DetectedElement)
                .filter(
                    DetectedElement.plan_id == plan_id,
                    DetectedElement.page == page,
                    DetectedElement.type == "opening",
                )
                .count()
            )
        existing_count_per_page[page] += 1
        display_label = label or f"Abertura {existing_count_per_page[page]}"

        element = DetectedElement(
            plan_id=plan_id,
            page=page,
            type="opening",
            geometry={
                "points": [p1[0], p1[1], p2[0], p2[1]],
                "label": display_label,
                "subtype": subtype,
            },
            length_m=width_m,
            height_m=2.1,
            source="ai",
        )
        db.add(element)
        created.append(element)

    if created:
        db.commit()
        for el in created:
            db.refresh(el)

    return created


# ---------------------------------------------------------------------------
# Asignación elemento ↔ sistema constructivo (assembly)
# ---------------------------------------------------------------------------
from app.models.material import Assembly  # noqa: E402
from app.schemas.assembly import (  # noqa: E402
    AssemblyAssignRequest,
    AssemblyBulkAssignRequest,
)

# applies_to del assembly → tipos de elemento a los que aplica. Permite
# "asignar a todos los muros" de un toque.
_APPLIES_TO_TYPES: dict[str, set[str]] = {
    "wall": {"wall"},
    "room_floor": {"room"}, "room_wall": {"room"}, "room_perimeter": {"room"},
    "opening": {"opening"}, "opening_perimeter": {"opening"},
    "beam": {"beam"}, "column": {"column"}, "roof": {"roof"},
    "riostra": {"riostra"}, "cloaca": {"cloaca"},
    "electricidad": {"electricidad"}, "escalera": {"escalera"},
}


def _plan_owned(plan_id: int, db: Session, user: User) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return plan


def _assembly_owned(assembly_id: int, db: Session, user: User) -> Assembly:
    asm = db.get(Assembly, assembly_id)
    if asm is None or asm.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Sistema constructivo no encontrado")
    return asm


@router.post(
    "/plans/{plan_id}/elements/{element_id}/assemblies",
    response_model=DetectedElementRead,
)
def assign_assembly(
    plan_id: int, element_id: int, payload: AssemblyAssignRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> DetectedElement:
    _plan_owned(plan_id, db, user)
    el = db.get(DetectedElement, element_id)
    if el is None or el.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    asm = _assembly_owned(payload.assembly_id, db, user)
    if asm not in el.assemblies:
        el.assemblies.append(asm)
        db.commit()
        db.refresh(el)
    return el


@router.delete(
    "/plans/{plan_id}/elements/{element_id}/assemblies/{assembly_id}",
    response_model=DetectedElementRead,
)
def remove_assembly(
    plan_id: int, element_id: int, assembly_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> DetectedElement:
    _plan_owned(plan_id, db, user)
    el = db.get(DetectedElement, element_id)
    if el is None or el.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    el.assemblies = [a for a in el.assemblies if a.id != assembly_id]
    db.commit()
    db.refresh(el)
    return el


@router.post(
    "/plans/{plan_id}/elements/bulk/assemblies",
    response_model=list[DetectedElementRead],
)
def bulk_assign_assembly(
    plan_id: int, payload: AssemblyBulkAssignRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    _plan_owned(plan_id, db, user)
    asm = _assembly_owned(payload.assembly_id, db, user)
    els = list(db.scalars(select(DetectedElement).where(
        DetectedElement.id.in_(payload.element_ids),
        DetectedElement.plan_id == plan_id,
    )).all())
    for el in els:
        if asm not in el.assemblies:
            el.assemblies.append(asm)
    db.commit()
    for el in els:
        db.refresh(el)
    return els


@router.post("/plans/{plan_id}/assemblies/{assembly_id}/assign-all")
def assign_assembly_to_all(
    plan_id: int, assembly_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """Asigna el sistema a TODOS los elementos del plan cuyo tipo matchea su
    `applies_to` (ej: "Muro Ladrillo" → todos los muros). Un solo click."""
    _plan_owned(plan_id, db, user)
    asm = _assembly_owned(assembly_id, db, user)
    target_types = _APPLIES_TO_TYPES.get(asm.applies_to, set())
    if not target_types:
        return {"assigned": 0, "types": []}
    els = list(db.scalars(select(DetectedElement).where(
        DetectedElement.plan_id == plan_id,
        DetectedElement.type.in_(target_types),
        DetectedElement.is_candidate.is_(False),
    )).all())
    n = 0
    for el in els:
        if asm not in el.assemblies:
            el.assemblies.append(asm)
            n += 1
    db.commit()
    return {"assigned": n, "types": sorted(target_types)}


@router.post("/plans/{plan_id}/assemblies/{assembly_id}/unassign-all")
def unassign_assembly_from_all(
    plan_id: int, assembly_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """Inverso de assign-all: quita el sistema de TODOS los elementos del plano
    cuyo tipo matchea su applies_to. Para deshacer una asignación masiva."""
    _plan_owned(plan_id, db, user)
    asm = _assembly_owned(assembly_id, db, user)
    target_types = _APPLIES_TO_TYPES.get(asm.applies_to, set())
    if not target_types:
        return {"removed": 0}
    els = list(db.scalars(select(DetectedElement).where(
        DetectedElement.plan_id == plan_id,
        DetectedElement.type.in_(target_types),
    )).all())
    n = 0
    for el in els:
        if any(a.id == assembly_id for a in el.assemblies):
            el.assemblies = [a for a in el.assemblies if a.id != assembly_id]
            n += 1
    db.commit()
    return {"removed": n}
