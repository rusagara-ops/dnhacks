from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Worker(Base):
    __tablename__ = 'workers'
    __table_args__ = (
        CheckConstraint('cpu_cores > 0', name='worker_cpu_positive'),
        CheckConstraint('ram_gb > 0', name='worker_ram_positive'),
        CheckConstraint('gpu_memory_gb IS NULL OR gpu_memory_gb >= 0', name='worker_gpu_memory_nonnegative'),
        CheckConstraint('gpu_core_count IS NULL OR gpu_core_count > 0', name='worker_gpu_cores_positive'),
        CheckConstraint("gpu_memory_kind IS NULL OR gpu_memory_kind IN ('unified','dedicated','unknown')", name='worker_memory_kind_valid'),
        CheckConstraint('ram_available_gb IS NULL OR (ram_available_gb >= 0 AND ram_available_gb <= ram_gb)', name='worker_available_ram_range'),
        CheckConstraint('gpu_available_gb IS NULL OR gpu_available_gb >= 0', name='worker_available_gpu_nonnegative'),
        CheckConstraint('gpu_model_memory_gb IS NULL OR gpu_model_memory_gb >= 0', name='worker_gpu_model_nonnegative'),
        CheckConstraint('benchmark_score > 0', name='worker_benchmark_positive'),
        CheckConstraint('cpu_utilization BETWEEN 0 AND 100', name='worker_cpu_utilization_range'),
        CheckConstraint('memory_utilization BETWEEN 0 AND 100', name='worker_memory_utilization_range'),
        CheckConstraint('active_tasks BETWEEN 0 AND 1', name='worker_single_task'),
        {'schema': 'coordinator'},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    hostname: Mapped[str] = mapped_column(Text)
    cpu: Mapped[str] = mapped_column(Text)
    cpu_cores: Mapped[int] = mapped_column(Integer)
    ram_gb: Mapped[float] = mapped_column(Float)
    gpu: Mapped[str | None] = mapped_column(Text)
    gpu_memory_gb: Mapped[float | None] = mapped_column(Float)
    gpu_core_count: Mapped[int | None] = mapped_column(Integer)
    gpu_memory_kind: Mapped[str | None] = mapped_column(Text)
    ram_available_gb: Mapped[float | None] = mapped_column(Float)
    gpu_available_gb: Mapped[float | None] = mapped_column(Float)
    gpu_model_memory_gb: Mapped[float | None] = mapped_column(Float)
    supported_tasks: Mapped[list[str]] = mapped_column(JSONB)
    model_id: Mapped[str | None] = mapped_column(Text)
    model_revision: Mapped[str | None] = mapped_column(Text)
    benchmark_score: Mapped[float] = mapped_column(Float, default=1)
    cpu_utilization: Mapped[float] = mapped_column(Float, default=0)
    memory_utilization: Mapped[float] = mapped_column(Float, default=0)
    active_tasks: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
