from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Job(Base):
    __tablename__ = 'jobs'
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','RUNNING','COMPLETED','FAILED')", name='job_status_valid'),
        CheckConstraint('total_inputs > 0 AND total_tasks > 0', name='job_totals_positive'),
        CheckConstraint('completed_tasks >= 0 AND failed_tasks >= 0 AND completed_tasks + failed_tasks <= total_tasks', name='job_counts_valid'),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_type: Mapped[str] = mapped_column(Text)
    optimization: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='QUEUED', server_default='QUEUED')
    total_inputs: Mapped[int] = mapped_column(Integer)
    total_tasks: Mapped[int] = mapped_column(Integer)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
