from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=200)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class WorkerRegisterRequest(InputModel):
    device_id: UUID | None = None
    name: Name
    hostname: Name
    cpu: Name
    cpu_cores: int = Field(gt=0, le=4096)
    ram_gb: Positive
    gpu: Name | None = None
    gpu_memory_gb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gpu_core_count: int | None = Field(default=None, gt=0, le=4096)
    gpu_memory_kind: Literal['unified', 'dedicated', 'unknown'] | None = None
    supported_tasks: list[Literal['sentiment-classification', 'summarization', 'document-qa', 'information-extraction', 'coding-assistance']] = Field(min_length=1, max_length=5)
    model_id: Name | None = None
    model_revision: Name | None = None
    benchmark_score: Positive = 1


class WorkerRegisterResponse(BaseModel):
    worker_id: UUID
    heartbeat_interval_seconds: int


class HeartbeatRequest(InputModel):
    task_id: UUID | None = None
    assignment_id: UUID | None = None

    @model_validator(mode='after')
    def assignment_pair(self):
        if bool(self.task_id) != bool(self.assignment_id):
            raise ValueError('Send both task_id and assignment_id')
        if self.task_id and self.active_tasks != 1:
            raise ValueError('An assignment heartbeat requires active_tasks=1')
        return self

    ram_available_gb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gpu_available_gb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gpu_model_memory_gb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cpu_utilization: Percent
    memory_utilization: Percent
    active_tasks: int = Field(ge=0, le=1)


class HeartbeatResponse(BaseModel):
    status: Literal['ok'] = 'ok'
    lease_expires_at: datetime | None = None


class WorkerResponse(WorkerRegisterRequest):
    id: UUID
    status: Literal['AVAILABLE', 'BUSY', 'OFFLINE']
    ram_available_gb: float | None = None
    gpu_available_gb: float | None = None
    gpu_model_memory_gb: float | None = None
    cpu_utilization: float
    memory_utilization: float
    active_tasks: int
    last_heartbeat: datetime
    created_at: datetime
    updated_at: datetime
