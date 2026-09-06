from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    role: Literal['member', 'admin'] = 'member'


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    role: str
    enabled: bool
    created_at: datetime


class WorkerCredentialCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    device_id: UUID
    label: str = Field(min_length=1, max_length=200)


class AccountCredentialCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=200)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    kind: str
    device_id: UUID | None
    label: str
    created_at: datetime
    revoked_at: datetime | None


class AccountCreated(BaseModel):
    account: AccountResponse
    token: str


class CredentialCreated(BaseModel):
    credential: CredentialResponse
    token: str
