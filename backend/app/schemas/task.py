from datetime import datetime
from uuid import UUID
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field


class TaskInput(BaseModel):
    index: int
    text: str


class TaskAssignment(BaseModel):
    task_id: UUID
    job_id: UUID
    assignment_id: UUID
    lease_expires_at: datetime
    task_type: str
    model_id: str
    model_revision: str
    inputs: list[TaskInput]


class NextTaskResponse(BaseModel):
    task: TaskAssignment | None


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    worker_id: UUID
    assignment_id: UUID


class Prediction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    index: Annotated[int, Field(ge=0, strict=True)]
    label: Literal['POSITIVE', 'NEGATIVE']
    score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class GeneratedText(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    index: Annotated[int, Field(ge=0, strict=True)]
    text: str = Field(min_length=1, max_length=4000)


class TaskCompleteRequest(AssignmentRequest):
    results: list[Prediction | GeneratedText] = Field(min_length=1, max_length=25)
    execution_time_ms: Annotated[int, Field(ge=0, strict=True)]


class TaskError(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class TaskFailRequest(AssignmentRequest):
    error: TaskError


class TaskMutationResponse(BaseModel):
    status: Literal['completed', 'already_completed', 'requeued', 'failed', 'already_failed']


class FailedTask(BaseModel):
    task_id: UUID
    input_start_index: int
    input_count: int
    error_code: str


class TaskDetail(BaseModel):
    task_id: UUID
    input_start_index: int
    input_count: int
    status: str
    worker_id: UUID | None
    worker_name: str | None
    attempt_count: int
    execution_time_ms: int | None


class JobResultResponse(BaseModel):
    job_id: UUID
    status: Literal['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED']
    is_final: bool
    total_inputs: int
    completed_inputs: int
    failed_inputs: int
    results: list[Prediction | GeneratedText]
    failed_tasks: list[FailedTask]

    tasks: list[TaskDetail] = Field(default_factory=list)
