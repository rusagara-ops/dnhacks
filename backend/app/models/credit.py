"""Demo-credit balances and their append-only accounting records.

Credits are an internal demonstration unit, not money or a payout promise.
The migration also protects ledger rows from UPDATE/DELETE at the database level.
"""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, event, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Wallet(Base):
    __tablename__ = 'wallets'
    __table_args__ = (
        CheckConstraint('available >= 0 AND reserved >= 0 AND lifetime_earned >= 0', name='wallet_balances_nonnegative'),
        {'schema': 'coordinator'},
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.accounts.id'), primary_key=True)
    available: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    reserved: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    lifetime_earned: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')


class CreditEntry(Base):
    __tablename__ = 'credit_entries'
    __table_args__ = (
        CheckConstraint("kind IN ('grant','reserve','spend','earn','refund')", name='credit_entry_kind_valid'),
        CheckConstraint(
            "(kind = 'grant' AND available_delta > 0 AND reserved_delta = 0 AND earned_delta = 0) OR "
            "(kind = 'reserve' AND available_delta < 0 AND reserved_delta = -available_delta AND earned_delta = 0) OR "
            "(kind = 'spend' AND available_delta = 0 AND reserved_delta < 0 AND earned_delta = 0) OR "
            "(kind = 'earn' AND available_delta > 0 AND reserved_delta = 0 AND earned_delta = available_delta) OR "
            "(kind = 'refund' AND available_delta > 0 AND reserved_delta = -available_delta AND earned_delta = 0)",
            name='credit_entry_deltas_valid',
        ),
        CheckConstraint(
            "(kind = 'grant' AND job_id IS NULL AND task_id IS NULL) OR "
            "(kind = 'reserve' AND job_id IS NOT NULL AND task_id IS NULL) OR "
            "(kind IN ('spend','earn','refund') AND job_id IS NOT NULL AND task_id IS NOT NULL)",
            name='credit_entry_references_valid',
        ),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.accounts.id'), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey('coordinator.jobs.id'), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey('coordinator.tasks.id'), index=True)
    kind: Mapped[str] = mapped_column(Text)
    available_delta: Mapped[int] = mapped_column(BigInteger)
    reserved_delta: Mapped[int] = mapped_column(BigInteger)
    earned_delta: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    pricing_version: Mapped[str] = mapped_column(Text, default='demo-v1', server_default='demo-v1')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


@event.listens_for(CreditEntry, 'before_update')
@event.listens_for(CreditEntry, 'before_delete')
def prevent_ledger_mutation(mapper, connection, target):
    raise ValueError('Credit ledger entries are immutable; record a compensating entry instead')
