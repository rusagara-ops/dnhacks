from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Name = Annotated[str, Field(min_length=1, max_length=200)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class WorkerRegisterRequest(InputModel):
    name: Name
    hostname: Name
    cpu: Name
    cpu_cores: int = Field(gt=0, le=4096)
    ram_gb: Positive
    gpu: Name | None = None
    gpu_memory_gb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    supported_tasks: list[Literal['sentiment-classification']] = Field(min_length=1, max_length=1)
    model_id: Name | None = None
    model_revision: Name | None = None
    benchmark_score: Positive = 1


class WorkerRegisterResponse(BaseModel):
    worker_id: UUID
    heartbeat_interval_seconds: int


class HeartbeatRequest(InputModel):
    cpu_utilization: Percent
    memory_utilization: Percent
    active_tasks: int = Field(ge=0, le=1)


class HeartbeatResponse(BaseModel):
    status: Literal['ok'] = 'ok'


class WorkerResponse(WorkerRegisterRequest):
    id: UUID
    status: Literal['AVAILABLE', 'BUSY', 'OFFLINE']
    cpu_utilization: float
    memory_utilization: float
    active_tasks: int
    last_heartbeat: datetime
    created_at: datetime
    updated_at: datetime
