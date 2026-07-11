from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

# PIVOTE IFC: imports DXF conservados para reactivación.
# from app.models.project import Project
# from app.services.dxf_import import build_dxf_plan

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post("/dxf/upload")
async def upload_dxf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # ─── PIVOTE IFC (jul-2026): DXF desactivado temporalmente.
    # Para REACTIVAR: quitar este raise y restaurar el cuerpo original debajo.
    _ = (file, db, user)
    raise HTTPException(
        status_code=400,
        detail=(
            "Por ahora solo aceptamos modelos BIM en formato .ifc. "
            "La carga de DXF está temporalmente deshabilitada."
        ),
    )

    # if not file.filename or not file.filename.lower().endswith(".dxf"):
    #     raise HTTPException(status_code=400, detail="El archivo debe ser un .dxf")
    # if not user.organization_id:
    #     raise HTTPException(status_code=403, detail="Usuario sin organización asignada")
    #
    # content = await file.read()
    #
    # project = Project(
    #     name=f"Importación AutoCAD: {file.filename}",
    #     description="Proyecto generado automáticamente desde archivo DXF.",
    #     status="active",
    #     wizard_step=5,
    #     organization_id=user.organization_id,
    #     user_id=user.id,
    # )
    # db.add(project)
    # db.flush()
    #
    # plan, elements_imported = build_dxf_plan(project.id, content, file.filename, db)
    #
    # db.commit()
    #
    # return {
    #     "success": True,
    #     "project_id": project.id,
    #     "plan_id": plan.id,
    #     "elements_imported": elements_imported,
    # }
