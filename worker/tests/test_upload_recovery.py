import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run


@pytest.mark.parametrize('scenario', ['upload_timeout', 'heartbeat_outage', 'ambiguous_then_conflict', 'lease_lost'])
def test_heartbeats_continue_and_upload_reuses_saved_result(scenario):
    generating = threading.Event()
    counts = {'predict': 0, 'heartbeat_during_generation': 0, 'register': 0}
    uploads = []
    task = {'task_id': 'task', 'assignment_id': 'assignment', 'model_id': 'gemma3:12b',
            'model_revision': 'digest', 'task_type': 'summarization', 'inputs': [{'index': 0, 'text': 'private source'}]}
    fake = SimpleNamespace(model_id='gemma3:12b', model_revision='digest', gpu_memory_gb=lambda: 1,
                           last_metrics={'prompt_tokens': 10, 'output_tokens': 2, 'generation_duration_ms': 100})

    def predict(assignment):
        counts['predict'] += 1
        generating.set()
        time.sleep(.12)
        generating.clear()
        return [{'index': 0, 'text': 'Saved summary'}]

    def handler(request):
        path = request.url.path
        if path.endswith('/register'):
            counts['register'] += 1
            return httpx.Response(201, json={'worker_id': 'worker', 'heartbeat_interval_seconds': .01})
        if path.endswith('/heartbeat'):
            payload = json.loads(request.content)
            if generating.is_set():
                counts['heartbeat_during_generation'] += 1
                assert payload['task_id'] == 'task' and payload['assignment_id'] == 'assignment'
                if scenario == 'heartbeat_outage': raise httpx.ReadTimeout('private transport diagnostic')
                if scenario == 'lease_lost': return httpx.Response(409)
            if scenario == 'ambiguous_then_conflict' and uploads: return httpx.Response(409)
            return httpx.Response(200, json={'status': 'ok'})
        if path.endswith('/next-task'): return httpx.Response(200, json={'task': task})
        assert path.endswith('/complete')
        uploads.append(request.content)
        if len(uploads) == 1 and scenario in ['upload_timeout', 'ambiguous_then_conflict']:
            raise httpx.ReadTimeout('private transport diagnostic')
        return httpx.Response(200, json={'status': 'already_completed' if len(uploads) > 1 else 'completed'})

    fake.predict = predict
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://test')
    args = SimpleNamespace(url='http://test', name='test', max_tasks=1, idle_timeout=1, poll_seconds=.03)
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'WORKER_STATE_DIR': directory}), \
         patch.object(run, 'Summarizer', return_value=fake), patch.object(run, 'hardware', return_value={}), \
         patch.object(run, 'memory_metrics', return_value={'cpu_utilization': 0, 'memory_utilization': 0}), \
         patch.object(run.httpx, 'AsyncClient', return_value=client):
        assert asyncio.run(run.run(args)) == 0
    assert counts['register'] == counts['predict'] == 1
    assert counts['heartbeat_during_generation'] >= 2
    if scenario == 'lease_lost':
        assert uploads == []
    else:
        assert len(uploads) == (2 if scenario in ['upload_timeout', 'ambiguous_then_conflict'] else 1)
        assert len(set(uploads)) == 1
        assert json.loads(uploads[0])['inference_metrics'] == fake.last_metrics
        assert json.loads(uploads[0])['assignment_id'] == 'assignment'
