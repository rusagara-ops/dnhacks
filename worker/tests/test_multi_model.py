import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run


def test_two_model_loops_share_one_registration(monkeypatch):
    models = []
    def load(name):
        model = SimpleNamespace(model_id=name, model_revision='digest', supported_tasks=['coding-assistance'], gpu_memory_gb=lambda: 1)
        models.append(model)
        return model
    monkeypatch.setattr(run, 'Summarizer', load)
    monkeypatch.setattr(run, 'hardware', lambda: {'ram_gb': 24})
    monkeypatch.setattr(run, 'device_id', lambda: 'stable-device')
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'worker_id': 'one-machine', 'heartbeat_interval_seconds': 5})
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return client
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(run.httpx, 'AsyncClient', Client)
    async def check():
        entered = []
        ready = asyncio.Event()
        async def lane(args, model, registration, pool):
            assert registration == ('one-machine', 5)
            assert len(pool) == 2
            entered.append(model.model_id)
            if len(entered) == 2: ready.set()
            await asyncio.wait_for(ready.wait(), 1)
        monkeypatch.setattr(run, 'run_locked', lane)
        await run.run_multi(SimpleNamespace(models=['gemma3:12b', 'qwen2.5-coder:3b'], name='Mac', url='http://test'))
        assert len(entered) == 2
    asyncio.run(check())
    assert client.post.await_count == 1
    assert len(client.post.call_args.kwargs['json']['models']) == 2
    assert run.gpu_allocation(models) == 2
