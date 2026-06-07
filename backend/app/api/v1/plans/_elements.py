from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import DetectedElement, Plan, User
from app.schemas.detected_element import (
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
