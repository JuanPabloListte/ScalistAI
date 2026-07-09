"""Seguimiento de Construcción: plan de obra persistido (baseline) + avances.

El cronograma que `services/schedule.py` calcula al vuelo se CONGELA acá como
baseline versionado. La regla de verdad única: si un proyecto tiene WorkPlan
activo, manda el plan persistido; el cálculo al vuelo queda como generador de
borradores. Re-programar = nueva versión (la anterior queda como historial).

Los derivados (% de avance, EVM, proyecciones) NO se persisten: se calculan
desde ProgressEntry/ActualCost contra el baseline, igual que el presupuesto.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Estados de flujo (tipo Jira) que fija el usuario a mano — independientes del
# avance físico derivado de cantidades. "blocked"/"cancelled" no se auto-calculan.
WORKFLOW_STATUSES = ("pending", "in_progress", "in_review",
                     "completed", "blocked", "cancelled")
TASK_PRIORITIES = ("low", "medium", "high", "critical")


class WorkPlan(Base):
    """Una versión del cronograma de obra de un proyecto.

    status: draft (borrador editable) → active (baseline congelado, inmutable)
    → superseded (reemplazado por una versión nueva) | closed (obra terminada).
    """
    __tablename__ = "work_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    crews: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    overlap_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    tasks: Mapped[list["WorkTask"]] = relationship(
        back_populates="work_plan", cascade="all, delete-orphan",
        order_by="WorkTask.stage_order, WorkTask.name")


class WorkTask(Base):
    """Tarea del plan. Las `source="auto"` nacen del cómputo (elementos ×
    recetas, vía compute_schedule); las `manual` las agrega el usuario.
    `depends_on`: ids de WorkTask precedentes (finish-to-start)."""
    __tablename__ = "work_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_plan_id: Mapped[int] = mapped_column(
        ForeignKey("work_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    assembly_id: Mapped[int | None] = mapped_column(
        ForeignKey("assemblies.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="Sin etapa")
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    qty_planned: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="un")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    planned_start: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[date] = mapped_column(Date, nullable=False)
    cost_planned: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    depends_on: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    # Flujo de trabajo (tipo Jira): metadata de EJECUCIÓN, no del baseline —
    # editable sobre el plan activo sin romper la inmutabilidad del cronograma.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    work_plan: Mapped["WorkPlan"] = relationship(back_populates="tasks")
    # Nav de solo lectura a la receta (para pre-acopio / recalibración de
    # rendimientos). Sin back_populates: Assembly no necesita conocer sus tareas.
    assembly: Mapped["object | None"] = relationship(
        "Assembly", foreign_keys=[assembly_id], viewonly=True)
    # Responsables (N por tarea, fiel al Gantt): M2M vía work_task_assignees.
    # No-viewonly → asignar la lista sincroniza las filas de la tabla puente.
    assignees: Mapped[list["object"]] = relationship(
        "User", secondary="work_task_assignees", lazy="selectin")
    progress_entries: Mapped[list["ProgressEntry"]] = relationship(
        back_populates="task", cascade="all, delete-orphan")
    events: Mapped[list["WorkTaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan",
        order_by="WorkTaskEvent.created_at.desc(), WorkTaskEvent.id.desc()")


class WorkTaskAssignee(Base):
    """Tabla puente tarea↔responsable (varios responsables por tarea)."""
    __tablename__ = "work_task_assignees"

    work_task_id: Mapped[int] = mapped_column(
        ForeignKey("work_tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class ProgressEntry(Base):
    """Registro de avance FÍSICO en unidades de obra (no en %): "hoy se
    colocaron 45 m²". El % se deriva (sum(qty_done)/qty_planned). Append-only:
    el historial de avance queda intacto."""
    __tablename__ = "progress_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("work_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    qty_done: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    task: Mapped["WorkTask"] = relationship(back_populates="progress_entries")


class WorkTaskEvent(Base):
    """Historial de cambios de una tarea (pestaña "Historial" del detalle):
    quién cambió qué y cuándo. Un evento por campo modificado; los comentarios
    sueltos van con field="comment". Append-only, base de la trazabilidad."""
    __tablename__ = "work_task_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_task_id: Mapped[int] = mapped_column(
        ForeignKey("work_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    task: Mapped["WorkTask"] = relationship(back_populates="events")
    author: Mapped["object | None"] = relationship(
        "User", foreign_keys=[created_by], viewonly=True, lazy="selectin")


class ActualCost(Base):
    """Costo REAL incurrido (factura/certificado/jornal), atribuible a una
    tarea o a una etapa. Base del avance financiero (EVM) y del desvío
    plan-vs-real ajustado por inflación."""
    __tablename__ = "actual_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    work_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_tasks.id", ondelete="SET NULL"), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="material")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class ObraShareLink(Base):
    """Link de solo lectura para el comitente: un token opaco que expone el
    reporte de avance de un proyecto SIN login. Revocable; se conserva el
    historial de tokens (revoked_at) pero solo uno queda activo por proyecto."""
    __tablename__ = "obra_share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
