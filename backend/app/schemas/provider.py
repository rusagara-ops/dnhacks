from typing import Literal
from pydantic import Field, model_validator
from app.schemas.worker import InputModel

TaskKind = Literal['sentiment-classification', 'summarization', 'document-qa', 'information-extraction', 'coding-assistance']
ALL_TASKS = ['sentiment-classification', 'summarization', 'document-qa', 'information-extraction', 'coding-assistance']


class AvailabilityWindow(InputModel):
    days: list[int] = Field(min_length=1, max_length=7)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @model_validator(mode='after')
    def valid_window(self):
        if any(day < 0 or day > 6 for day in self.days) or len(set(self.days)) != len(self.days):
            raise ValueError('Days must be unique Monday=0 through Sunday=6')
        if self.start_minute >= self.end_minute:
            raise ValueError('End must follow start; split overnight availability into two windows')
        return self


class ProviderPolicyUpdate(InputModel):
    sharing_enabled: bool
    allowed_task_types: list[TaskKind] = Field(max_length=5)
    max_concurrent_tasks: int = Field(ge=1, le=2)
    min_ram_available_gb: float = Field(ge=0, le=1048576, allow_inf_nan=False)
    availability: list[AvailabilityWindow] = Field(default_factory=list, max_length=28)

    @model_validator(mode='after')
    def unique_tasks(self):
        if len(set(self.allowed_task_types)) != len(self.allowed_task_types):
            raise ValueError('Choose each workload once')
        return self
