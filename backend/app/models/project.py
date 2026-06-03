from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.plan import Plan
    from app.models.user import User
    from app.models.organization import Organization


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    wizard_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Localizacion (paso 3 del wizard)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Tipo de construccion + info especifica (paso 4)
    # building_type: 'casa' | 'edificio' | 'condominio' | 'comercial'
    # building_info: dict con claves dependientes del tipo (ver schemas/project.py)
    building_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    building_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Si True, los planos confirmados de este proyecto pueden usarse como
    # datos de entrenamiento (vía synthetic_generator). Cliente con NDA
    # estricto debe ponerlo en False antes de activar el proyecto.
    allow_training_data: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    organization: Mapped["Organization"] = relationship(back_populates="projects")
    plans: Mapped[list["Plan"]] = relationship(back_populates="project", cascade="all, delete-orphan")
