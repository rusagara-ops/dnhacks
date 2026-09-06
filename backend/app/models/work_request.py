from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class WorkRequest(Base):
    """A provider-approved lane for a member's next job."""

    __tablename__ = 'work_requests'
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPROVED','DECLINED','USED','EXPIRED')", name='work_request_status_valid'),
        CheckConstraint('requester_account_id <> provider_account_id', name='work_request_distinct_accounts'),
        Index('ix_work_requests_requester_account_id', 'requester_account_id'),
        Index('ix_work_requests_provider_account_id', 'provider_account_id'),
        Index('ix_work_requests_worker_id', 'worker_id'),
        Index('ix_work_requests_status', 'status'),
        {'schema': 'coordinator'},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    requester_account_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.accounts.id'))
    provider_account_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.accounts.id'))
    worker_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.workers.id'))
    task_type: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='PENDING', server_default='PENDING')
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey('coordinator.jobs.id'), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
