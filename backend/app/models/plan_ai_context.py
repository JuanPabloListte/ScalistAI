from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.plan import Plan

class PlanAiContext(Base):
    __tablename__ = "plan_ai_contexts"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Provider used for this context (e.g., 'gemini', 'anthropic')
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    
    # Store messages / history / analysis as JSON
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["Plan"] = relationship("Plan", back_populates="ai_context")
