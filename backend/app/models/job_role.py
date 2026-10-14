"""Roles de obra (oficios) por organización — independientes de admin/member."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


user_job_roles = Table(
    "user_job_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("job_role_id", ForeignKey("job_roles.id", ondelete="CASCADE"), primary_key=True),
)


# Catálogo inicial al crear/sembrar roles de una org (AR / obra).
DEFAULT_JOB_ROLE_NAMES: tuple[str, ...] = (
    "Director de obra",
    "Jefe de obra",
    "Maestro de obra",
    "Capataz",
    "Arquitecto",
    "Ingeniero civil",
    "Calculista",
    "Oficial albañil",
    "Albañil",
    "Ayudante albañil",
    "Peón / Ayudante general",
    "Encofrador",
    "Armador / Fierrero",
    "Hormigonero",
    "Yesero / Revoquista",
    "Durlockero / Tabiquería",
    "Pintor",
    "Ceramista / Alicatador",
    "Impermeabilizador",
    "Techista",
    "Carpintero",
    "Herrero / Metalúrgico",
    "Soldador",
    "Electricista",
    "Ayudante electricista",
    "Plomero",
    "Gasista",
    "Instalador de aberturas",
    "Vidriero",
    "Climatización / Aire acondicionado",
    "Ascensorista",
    "Operador de maquinaria",
    "Topógrafo / Agrimensor",
    "Higiene y seguridad",
    "Administrativo de obra",
    "Compras / Logística",
    "Chofer / Flete",
    "Paisajista / Jardinería",
    "Demoledor",
)


class JobRole(Base):
    """Rol de oficio/función en obra, catalogado por organización."""

    __tablename__ = "job_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_job_roles_org_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    organization: Mapped["Organization"] = relationship(back_populates="job_roles")
    users: Mapped[list["User"]] = relationship(
        secondary=user_job_roles, back_populates="job_roles",
    )
