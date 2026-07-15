"""Resolución de acceso a un proyecto: qué puede hacer este usuario acá.

Una sola fuente de verdad para los permisos por proyecto. La regla que ordena
todo es **quién ve la plata**: el capataz registra avance pero no ve márgenes;
el comitente ve avance pero ningún financiero.

Precedencia:
    1. superadmin              → todo
    2. admin de la org         → todo (sobre proyectos de SU org, sin membresía)
    3. miembro del proyecto    → según su rol (jefe_obra / capataz / comitente)
    4. proyecto SIN miembros   → retrocompatible: cualquiera de la org, todo
    5. resto                   → sin acceso

El punto 4 es deliberado: hoy cualquier miembro de la org ve todos los
proyectos. Exigir membresía de golpe dejaría a todos afuera. Mientras un
proyecto no tenga miembros asignados se comporta como antes; en cuanto le
asignás gente, empieza a regir la membresía.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User


@dataclass(frozen=True)
class ProjectAccess:
    """Permisos efectivos de un usuario sobre un proyecto."""

    role: str                    # admin | jefe_obra | capataz | comitente
    can_view: bool
    can_view_financials: bool    # presupuesto, costos, EVM, márgenes, reporte interno
    can_edit_plan: bool          # generar/congelar/reprogramar, editar tareas
    can_register_progress: bool  # cargar avance físico
    can_manage_members: bool

    @property
    def is_client(self) -> bool:
        """Comitente: solo lectura y sin financieros (mismo criterio que el PDF)."""
        return self.role == "comitente"


_FULL = dict(
    can_view=True, can_view_financials=True, can_edit_plan=True,
    can_register_progress=True, can_manage_members=True,
)

# La matriz. Cambiar permisos = tocar SOLO esto.
_BY_ROLE: dict[str, dict] = {
    "jefe_obra": dict(
        can_view=True, can_view_financials=True, can_edit_plan=True,
        can_register_progress=True, can_manage_members=True,
    ),
    "capataz": dict(
        can_view=True, can_view_financials=False, can_edit_plan=False,
        can_register_progress=True, can_manage_members=False,
    ),
    "comitente": dict(
        can_view=True, can_view_financials=False, can_edit_plan=False,
        can_register_progress=False, can_manage_members=False,
    ),
}


def get_access(project: Project, user: User, db: Session) -> ProjectAccess:
    """Permisos efectivos (no lanza; `can_view=False` si no tiene acceso)."""
    if user.is_superadmin:
        return ProjectAccess(role="admin", **_FULL)

    same_org = (
        user.organization_id is not None
        and project.organization_id == user.organization_id
    )
    if not same_org:
        return ProjectAccess(
            role="none", can_view=False, can_view_financials=False,
            can_edit_plan=False, can_register_progress=False,
            can_manage_members=False,
        )

    if user.org_role == "admin":
        return ProjectAccess(role="admin", **_FULL)

    membership = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    ).first()
    if membership is not None:
        perms = _BY_ROLE.get(membership.role)
        if perms is None:  # rol desconocido → conservador: solo lectura
            perms = _BY_ROLE["comitente"]
        return ProjectAccess(role=membership.role, **perms)

    # Sin membresía: si el proyecto NO tiene miembros, vale el comportamiento
    # histórico (org member = acceso completo). Si tiene, este usuario no entra.
    has_members = db.scalar(
        select(ProjectMember.id).where(ProjectMember.project_id == project.id).limit(1)
    )
    if has_members is None:
        return ProjectAccess(role="jefe_obra", **_BY_ROLE["jefe_obra"])

    return ProjectAccess(
        role="none", can_view=False, can_view_financials=False,
        can_edit_plan=False, can_register_progress=False, can_manage_members=False,
    )


def require_project(
    project_id: int, db: Session, user: User, *,
    financials: bool = False,
    edit_plan: bool = False,
    register_progress: bool = False,
    manage_members: bool = False,
) -> tuple[Project, ProjectAccess]:
    """Carga el proyecto y exige los permisos pedidos.

    404 si no existe o no es visible (no filtramos existencia); 403 si lo ve
    pero le falta el permiso puntual.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    access = get_access(project, user, db)
    if not access.can_view:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if financials and not access.can_view_financials:
        raise HTTPException(
            status_code=403,
            detail="Tu rol en este proyecto no tiene acceso a la información económica.",
        )
    if edit_plan and not access.can_edit_plan:
        raise HTTPException(
            status_code=403,
            detail="Tu rol en este proyecto no permite modificar el plan de obra.",
        )
    if register_progress and not access.can_register_progress:
        raise HTTPException(
            status_code=403,
            detail="Tu rol en este proyecto no permite registrar avance.",
        )
    if manage_members and not access.can_manage_members:
        raise HTTPException(
            status_code=403,
            detail="Tu rol en este proyecto no permite gestionar el equipo.",
        )
    return project, access


def list_members(project_id: int, db: Session) -> list[ProjectMember]:
    return list(db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id)
    ).all())


def set_member(project: Project, user_id: int, role: str, db: Session) -> ProjectMember:
    """Alta o cambio de rol. Valida que el usuario sea de la misma org."""
    from app.models.project_member import PROJECT_ROLES

    if role not in PROJECT_ROLES:
        raise ValueError(f"Rol inválido: {role}. Válidos: {', '.join(PROJECT_ROLES)}")
    member_user = db.get(User, user_id)
    if member_user is None or member_user.organization_id != project.organization_id:
        raise ValueError("El usuario no pertenece a tu organización.")

    existing = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    if existing is not None:
        existing.role = role
        db.flush()
        return existing
    row = ProjectMember(project_id=project.id, user_id=user_id, role=role)
    db.add(row)
    db.flush()
    return row


def remove_member(project_id: int, user_id: int, db: Session) -> bool:
    row = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
