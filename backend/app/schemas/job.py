from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_type: Literal['sentiment-classification']
    inputs: list[Annotated[str, Field(min_length=1, max_length=10000)]] = Field(min_length=1, max_length=1000)
    optimization: Literal['fastest'] = 'fastest'

    @field_validator('inputs')
    @classmethod
    def nonblank_inputs(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError('Inputs must not be blank')
        return values  # Preserve original text, including whitespace.

    @model_validator(mode='after')
    def bounded_payload(self):
        if sum(len(value.encode('utf-8')) for value in self.inputs) > 1_000_000:
            raise ValueError('Combined input text must not exceed 1,000,000 UTF-8 bytes')
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_type: str
    optimization: str
    status: Literal['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED']
    total_inputs: int
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    progress_percentage: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class JobCreateResponse(BaseModel):
    job_id: UUID
    status: Literal['QUEUED'] = 'QUEUED'
    total_inputs: int
    total_tasks: int
