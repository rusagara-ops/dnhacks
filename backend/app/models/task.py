from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','ASSIGNED','RUNNING','COMPLETED','FAILED')", name='task_status_valid'),
        CheckConstraint('start_index >= 0 AND input_count BETWEEN 1 AND 25', name='task_chunk_valid'),
        CheckConstraint('attempt_count BETWEEN 0 AND 3', name='task_attempts_valid'),
        UniqueConstraint('job_id', 'start_index', name='task_job_start_unique'),
        Index('uq_tasks_active_worker', 'assigned_worker_id', unique=True, postgresql_where=text("status IN ('ASSIGNED','RUNNING')")),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.jobs.id', ondelete='CASCADE'), index=True)
    start_index: Mapped[int] = mapped_column(Integer)
    input_count: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default='QUEUED', server_default='QUEUED', index=True)
    assigned_worker_id: Mapped[UUID | None] = mapped_column(ForeignKey('coordinator.workers.id'), index=True)
    assignment_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
