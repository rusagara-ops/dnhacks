from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


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
