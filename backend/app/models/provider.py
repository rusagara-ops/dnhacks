from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class ProviderPolicy(Base):
    __tablename__ = 'provider_policies'
    __table_args__ = (
        CheckConstraint('max_concurrent_tasks BETWEEN 1 AND 2', name='provider_concurrency_range'),
        CheckConstraint('min_ram_available_gb >= 0', name='provider_ram_nonnegative'),
        {'schema': 'coordinator'},
    )
    worker_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.workers.id', ondelete='CASCADE'), primary_key=True)
    sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    allowed_task_types: Mapped[list] = mapped_column(JSONB)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=1)
    min_ram_available_gb: Mapped[float] = mapped_column(Float, default=0)
    availability: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExecutionAttempt(Base):
    __tablename__ = 'execution_attempts'
    __table_args__ = (
        CheckConstraint("status IN ('ASSIGNED','COMPLETED','FAILED','EXPIRED')", name='attempt_status_valid'),
        CheckConstraint('reported_execution_ms IS NULL OR reported_execution_ms >= 0', name='attempt_runtime_nonnegative'),
        {'schema': 'coordinator'},
    )
    assignment_id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.tasks.id', ondelete='CASCADE'), index=True)
    worker_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.workers.id', ondelete='CASCADE'), index=True)
    status: Mapped[str] = mapped_column(Text, default='ASSIGNED')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_execution_ms: Mapped[int | None] = mapped_column(Integer)
