import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_superadmin
from app.models import Plan, User

router = APIRouter(tags=["plans"])


@router.get("/plans/training-stats")
def get_training_stats(
    user: User = Depends(get_current_user),
) -> dict:
    """Estadísticas del corpus de variaciones sintéticas acumulado."""
    base = Path(settings.STORAGE_DIR) / "synthetic"
    total_samples = 0
    total_batches = 0
    plans_contributing: set[int] = set()
    projects_contributing: set[int] = set()
    latest_snapshot: str | None = None

    if base.exists():
        for manifest_path in base.rglob("_manifest.json"):
            total_batches += 1
            try:
                m = _json.loads(manifest_path.read_text())
            except Exception:  # noqa: BLE001
                continue
            total_samples += int(m.get("num_variations", 0))
            if (pid := m.get("plan_id")) is not None:
                plans_contributing.add(pid)
            if (proj_id := m.get("project_id")) is not None:
                projects_contributing.add(proj_id)
            snap = m.get("snapshot_at")
            if snap and (latest_snapshot is None or snap > latest_snapshot):
                latest_snapshot = snap

    return {
        "total_samples": total_samples,
        "total_batches": total_batches,
        "plans_contributing": len(plans_contributing),
        "projects_contributing": len(projects_contributing),
        "latest_snapshot_at": latest_snapshot,
        "ready_to_train": total_samples >= 200,
        "recommended_min_samples": 200,
    }


@router.post("/plans/{plan_id}/generate-synthetic")
def generate_synthetic_dataset(
    plan_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Genera N variaciones sintéticas de una página para el dataset de fine-tuning."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    try:
        page = int(payload.get("page", 1))
        num_variations = int(payload.get("num_variations", 50))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="page y num_variations deben ser enteros")

    if num_variations < 1 or num_variations > 500:
        raise HTTPException(status_code=400, detail="num_variations debe estar entre 1 y 500")

    from app.services.synthetic_generator import generate_synthetic_variations

    try:
        metas = generate_synthetic_variations(plan_id, page, num_variations)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error generando variaciones: {exc}") from exc

    return {
        "plan_id": plan_id,
        "page": page,
        "variations_generated": len(metas),
        "sample": metas[:5],
    }





@router.post("/admin/train-now")
def trigger_training(
    epochs: int = 10,
    user: User = Depends(require_superadmin),
) -> dict:
    """Dispara el re-entrenamiento del modelo ML en background."""
    _ = user  # autenticado via require_superadmin
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    res = manager.start_training(epochs=epochs)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@router.post("/admin/gen-procedural")
def trigger_procedural_generation(
    count: int = 3000,
    user: User = Depends(require_superadmin),
) -> dict:
    """Genera el dataset PROCEDURAL en background."""
    _ = user
    if count < 100 or count > 50000:
        raise HTTPException(status_code=400, detail="count debe estar entre 100 y 50000.")
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    res = manager.start_procedural(count=count)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@router.get("/admin/train-status")
def get_training_status(
    user: User = Depends(require_superadmin),
) -> dict:
    """Devuelve estado y logs del entrenamiento en background."""
    _ = user
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    return {
        "status": manager.get_status(),
        "logs": manager.get_logs(limit=200),
    }
