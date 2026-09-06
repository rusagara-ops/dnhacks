from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env', extra='ignore'
    )
    inference_model_id: str | None = Field(default=None, min_length=1)
    inference_model_revision: str | None = Field(default=None, min_length=1)
    compute_origin_latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    compute_origin_longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    task_max_runtime_seconds: int = Field(default=1800, ge=30, le=86400)
    recovery_interval_seconds: int = Field(default=5, ge=1, le=60)
    task_lease_seconds: int = Field(default=300, ge=30, le=3600)
    database_url: SecretStr | None = None
    auth_mode: Literal['demo', 'controlled'] = 'demo'
    api_token: SecretStr | None = None
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    heartbeat_interval_seconds: int = Field(default=5, ge=1)
    worker_timeout_seconds: int = Field(default=15, ge=1)

    @model_validator(mode='after')
    def validate_timeout(self):
        if (self.compute_origin_latitude is None) != (self.compute_origin_longitude is None):
            raise ValueError('Set both compute origin latitude and longitude, or neither')
        if self.task_max_runtime_seconds < self.task_lease_seconds:
            raise ValueError('Maximum task runtime must be at least the lease duration')
        if bool(self.inference_model_id) != bool(self.inference_model_revision):
            raise ValueError('Set both inference model ID and revision, or neither')
        if self.worker_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError('Worker timeout must be longer than the heartbeat interval')
        if self.api_token is not None and not self.api_token.get_secret_value():
            self.api_token = None
        return self
