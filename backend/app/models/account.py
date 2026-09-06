from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Account(Base):
    __tablename__ = 'accounts'
    __table_args__ = (
        CheckConstraint("role IN ('member','admin')", name='account_role_valid'),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default='member', server_default='member')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default='true')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Credential(Base):
    __tablename__ = 'credentials'
    __table_args__ = (
        CheckConstraint("kind IN ('account','worker')", name='credential_kind_valid'),
        CheckConstraint("(kind = 'worker' AND device_id IS NOT NULL) OR (kind = 'account' AND device_id IS NULL)", name='credential_device_scope_valid'),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey('coordinator.accounts.id'), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    device_id: Mapped[UUID | None] = mapped_column(index=True)
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
