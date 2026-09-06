import math
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inference import generation_metrics
from location import location_from_args


def test_generation_metrics_use_actual_token_generation_time():
    assert generation_metrics([{'prompt_eval_count': 30, 'eval_count': 10, 'eval_duration': 2_000_000_000,
                                'total_duration': 9_000_000_000},
                               {'prompt_eval_count': 40, 'eval_count': 20, 'eval_duration': 1_000_000_000}]) == {
        'prompt_tokens': 70, 'output_tokens': 30, 'generation_duration_ms': 3000}


@pytest.mark.parametrize('unknown', [None, -1, '20', True, float('inf'), float('nan')])
def test_missing_or_invalid_measurements_are_null(unknown):
    result = generation_metrics([{'prompt_eval_count': 20, 'eval_count': unknown, 'eval_duration': unknown}])
    assert result == {'prompt_tokens': 20, 'output_tokens': None, 'generation_duration_ms': None}
    assert all(value is None for value in generation_metrics([]).values())


def test_worker_location_is_optional_and_zero_is_valid():
    assert location_from_args(SimpleNamespace()) is None
    assert location_from_args(SimpleNamespace(site=' Campus ', latitude=0, longitude=0)) == {
        'site': 'Campus', 'region': None, 'latitude': 0, 'longitude': 0}


@pytest.mark.parametrize('changes', [{'latitude': None}, {'longitude': math.nan}, {'longitude': 181}, {'site': ' '}])
def test_invalid_worker_location_fails_before_model_loading(changes):
    with pytest.raises(ValueError):
        location_from_args(SimpleNamespace(**({'site': 'Campus', 'latitude': 0, 'longitude': 0} | changes)))


def test_registered_model_stays_resident_after_warmup_and_inference(monkeypatch):
    import inference
    resident = {'value': False}
    def response(data):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    def get(url, **kwargs):
        if url.endswith('/api/tags'):
            return response({'models': [{'name': 'gemma3:12b', 'digest': 'test'}]})
        return response({'models': [{'digest': 'test', 'size_vram': 100}] if resident['value'] else []})
    def post(url, json, **kwargs):
        resident['value'] = isinstance(json.get('keep_alive'), int) and json['keep_alive'] < 0
        return response({'done': True, 'message': {'content': 'A short summary.'}})
    monkeypatch.setattr(inference.httpx, 'get', get)
    monkeypatch.setattr(inference.httpx, 'post', post)
    model = inference.Summarizer()
    model.predict({'model_id': 'gemma3:12b', 'model_revision': 'test', 'task_type': 'summarization',
                   'inputs': [{'index': 0, 'text': 'A brief document.'}]})
    assert model.gpu_memory_gb() > 0


def test_mac_identity_survives_repository_copy_and_preserves_migration_alias(monkeypatch, tmp_path):
    import hardware
    from uuid import uuid4
    monkeypatch.delenv('WORKER_STATE_DIR', raising=False)
    monkeypatch.setattr(hardware.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(hardware.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout='"IOPlatformUUID" = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"'))
    first = tmp_path / 'first'; first.mkdir()
    monkeypatch.setattr(hardware, '__file__', str(first / 'hardware.py'))
    (first / '.cache').mkdir(); old = str(uuid4()); (first / '.cache/device-id').write_text(old)
    identity = hardware.device_id()
    assert hardware.previous_device_id() == old
    second = tmp_path / 'second'; second.mkdir()
    monkeypatch.setattr(hardware, '__file__', str(second / 'hardware.py'))
    assert hardware.device_id() == identity
