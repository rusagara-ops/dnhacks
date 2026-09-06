from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.core.config import Settings
from app.core.model_registry import select_model
from app.schemas.job import JobCreateRequest
from app.services.eligibility import eligibility_reasons

NOW = datetime.now(timezone.utc)

def worker(**overrides):
    values = dict(last_heartbeat=NOW, active_tasks=0, supported_tasks=['summarization'],
                  model_id='gemma3:12b', model_revision='digest', ram_gb=24,
                  ram_available_gb=4, cpu_utilization=10, gpu='Apple GPU',
                  gpu_model_memory_gb=8, gpu_memory_kind='unified', gpu_available_gb=None)
    return SimpleNamespace(**(values | overrides))

def reasons(**overrides):
    return eligibility_reasons(worker(**overrides), 'gemma3:12b', 'digest', 'summarization', NOW, 15)

def test_unified_memory_headroom():
    assert reasons() == []
    assert reasons(ram_available_gb=1) == ['FREE_RAM_INSUFFICIENT']
    assert reasons(ram_available_gb=None) == ['FREE_RAM_UNKNOWN']
    assert 'GPU_MODEL_NOT_CONFIRMED' in reasons(gpu_model_memory_gb=0)

def test_capability_and_current_load():
    assert reasons(cpu_utilization=90) == ['CPU_OVERLOADED']
    assert reasons(active_tasks=1) == ['BUSY']
    assert reasons(model_revision='other') == ['MODEL_MISMATCH']
    assert reasons(supported_tasks=['coding-assistance']) == ['TASK_UNSUPPORTED']
    assert 'FREE_VRAM_UNKNOWN' in reasons(gpu_memory_kind='dedicated')
    assert 'FREE_VRAM_INSUFFICIENT' in reasons(gpu_memory_kind='dedicated',gpu_available_gb=.5)
    assert reasons(gpu_memory_kind='dedicated',gpu_available_gb=2) == []

def test_explicit_selection_and_legacy_omission():
    settings = Settings(_env_file=None,inference_model_id='gemma3:12b',inference_model_revision='digest')
    payload = JobCreateRequest(task_type='summarization',inputs=['document'],model_id='gemma3:12b')
    assert select_model(payload,settings) == ('gemma3:12b','digest')
    for model,code in [('unknown',422),('simulation/ui',503)]:
        with pytest.raises(HTTPException) as exc:
            select_model(payload.model_copy(update={'model_id':model}),settings)
        assert exc.value.status_code == code
    with pytest.raises(HTTPException) as exc:
        select_model(payload.model_copy(update={'task_type':'sentiment-classification'}),settings)
    assert exc.value.status_code == 422
    assert select_model(payload.model_copy(update={'model_id':None}),settings) == ('gemma3:12b','digest')


def test_model_catalog_uses_demo_auth_and_reports_configuration():
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = Settings(_env_file=None, database_url=None, api_token='test-token',
                        inference_model_id='simulation/ui', inference_model_revision='v1')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/models').status_code == 401
        response = client.get('/api/models', headers={'Authorization':'Bearer test-token'})
        assert response.status_code == 200
        configured = [model for model in response.json() if model['configured']]
        assert len(configured) == 1
        assert configured[0]['model_id'] == 'simulation/ui'
        assert configured[0]['model_revision'] == 'v1'
