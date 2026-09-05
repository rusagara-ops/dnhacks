from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_type: Literal['sentiment-classification', 'summarization', 'document-qa', 'information-extraction', 'coding-assistance']
    inputs: list[Annotated[str, Field(min_length=1, max_length=10000)]] = Field(min_length=1, max_length=1000)
    instruction: str | None = Field(default=None, min_length=1, max_length=1000)
    optimization: Literal['fastest'] = 'fastest'

    @field_validator('inputs')
    @classmethod
    def nonblank_inputs(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError('Inputs must not be blank')
        return values  # Preserve original text, including whitespace.

    @model_validator(mode='after')
    def bounded_payload(self):
        if self.task_type == 'document-qa' and not (self.instruction or '').strip():
            raise ValueError('Document Q&A requires a question in instruction')
        if self.instruction is not None and (not self.instruction.strip() or self.task_type not in ['document-qa', 'coding-assistance']):
            raise ValueError('Instruction is only supported for Q&A and coding assistance and must not be blank')
        if self.task_type != 'sentiment-classification' and any(len(value.encode('utf-8')) > 6000 for value in self.inputs):
            raise ValueError('Each document or code snippet must be at most 6,000 UTF-8 bytes')
        if self.instruction and any(len(value.encode('utf-8')) + len(self.instruction.encode('utf-8')) > 6500 for value in self.inputs):
            raise ValueError('Each input plus instruction must be at most 6,500 UTF-8 bytes')
        if sum(len(value.encode('utf-8')) for value in self.inputs) > 1_000_000:
            raise ValueError('Combined input text must not exceed 1,000,000 UTF-8 bytes')
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_type: str
    model_id: str | None
    model_revision: str | None
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
