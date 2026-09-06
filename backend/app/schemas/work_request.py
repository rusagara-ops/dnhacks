from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.provider import TaskKind


class WorkRequestCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider_account_id: UUID
    worker_id: UUID
    task_type: TaskKind
    model_id: str | None = Field(default=None, min_length=1, max_length=200)


class WorkRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    requester_account_id: UUID
    requester_name: str
    provider_account_id: UUID
    provider_name: str
    worker_id: UUID
    worker_name: str
    task_type: str
    model_id: str | None
    status: Literal['PENDING', 'APPROVED', 'DECLINED', 'USED', 'EXPIRED']
    job_id: UUID | None
    created_at: datetime
    decided_at: datetime | None
    used_at: datetime | None


class ProviderDirectoryItem(BaseModel):
    provider_account_id: UUID
    provider_name: str
    worker_id: UUID
    worker_name: str
    accepting_new_tasks: bool
    task_types: list[str]
    models: list[dict]
    active_tasks: int
    max_concurrent_tasks: int
    admission_reasons: list[str]

