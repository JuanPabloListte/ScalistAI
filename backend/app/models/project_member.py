"""Membresía por PROYECTO: quién participa y con qué nivel de acceso.

Es el eje de PERMISOS (qué podés hacer), distinto del oficio (`JobRole`, qué
hacés en obra: albañil, electricista...). Un mismo albañil puede ser `capataz`
en una obra y no estar en otra; el oficio no cambia, el permiso sí.

Roles y la línea que importa —**quién ve la plata**:
    jefe_obra  → todo el proyecto (presupuesto, costos, plan, avance)
    capataz    → registra avance y ve el cronograma SIN importes
    comitente  → solo lectura de avance/cronograma, SIN nada financiero

El admin de la organización tiene acceso total a sus proyectos sin necesidad de
membresía. Retrocompatible: un proyecto SIN miembros se comporta como antes
(cualquier miembro de la org lo ve completo) — ver services/project_access.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


# Roles de permiso DENTRO de un proyecto (no confundir con org_role admin/member
# ni con JobRole/oficio).
PROJECT_ROLES: tuple[str, ...] = ("jefe_obra", "capataz", "comitente")

PROJECT_ROLE_LABELS: dict[str, str] = {
    "jefe_obra": "Jefe de obra",
    "capataz": "Capataz",
    "comitente": "Comitente",
}


class ProjectMember(Base):
    """Un usuario participando de un proyecto con un rol de permiso."""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="capataz")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(lazy="selectin")
