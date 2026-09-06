from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class TaskResult(Base):
    __tablename__ = 'task_results'
    __table_args__ = (CheckConstraint('execution_time_ms >= 0', name='result_duration_nonnegative'), {'schema': 'coordinator'})
    task_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.tasks.id', ondelete='CASCADE'), primary_key=True)
    worker_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.workers.id'), index=True)
    result: Mapped[list] = mapped_column(JSONB)
    inference_metrics: Mapped[dict | None] = mapped_column(JSONB)
    execution_time_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
