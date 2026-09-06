from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreditQuote(BaseModel):
    total_inputs: int
    credits: int
    unit: Literal['demo credits'] = 'demo credits'
    pricing_version: Literal['demo-v1'] = 'demo-v1'


class CreditGrantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: UUID
    amount: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    request_id: UUID


class CreditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID | None
    task_id: UUID | None
    kind: Literal['grant', 'reserve', 'spend', 'earn', 'refund']
    available_delta: int
    reserved_delta: int
    earned_delta: int
    pricing_version: str
    created_at: datetime


class CreditBalanceResponse(BaseModel):
    account_id: UUID
    available: int
    reserved: int
    lifetime_earned: int
    unit: Literal['demo credits'] = 'demo credits'
    pricing_version: Literal['demo-v1'] = 'demo-v1'
    entries: list[CreditEntryResponse]
    total_entries: int
