from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Worker, Task
from app.schemas.job import JobCreateRequest
from app.schemas.task import TaskCompleteRequest
from app.services.job_service import create_job
from app.services.scheduler import get_next_task
from app.services.task_service import complete_task
from app.services.recovery import recover_expired
from test_scheduler_postgres import factory, seed, SETTINGS


def test_model_slots_claim_complete_and_recover_independently(factory):
    worker = seed(factory)[0]
    with factory.begin() as db:
        w = db.get(Worker, worker)
        w.models = [{'model_id': m, 'model_revision': 'v1', 'supported_tasks': ['coding-assistance']} for m in ['gemma3:12b', 'qwen2.5-coder:3b']]
        w.model_id, w.model_revision = 'gemma3:12b', 'v1'
        w.supported_tasks = ['coding-assistance']
        w.ram_gb = 24
        w.ram_available_gb = 4
        w.gpu = 'Apple GPU'
        w.gpu_memory_kind = 'unified'
        w.gpu_model_memory_gb = 10
    for model in ['gemma3:12b', 'qwen2.5-coder:3b', 'qwen2.5-coder:3b']:
        with factory() as db:
            create_job(db, JobCreateRequest(task_type='coding-assistance', inputs=['print(1)'], model_id=model))
    def claim(model):
        with factory() as db:
            return get_next_task(db, worker, SETTINGS, model).task
    a, b = claim('gemma3:12b'), claim('qwen2.5-coder:3b')
    assert a and b and a.task_id != b.task_id
    assert claim('qwen2.5-coder:3b').assignment_id == b.assignment_id
    with factory() as db:
        assert db.get(Worker, worker).active_tasks == 2
        complete_payload = TaskCompleteRequest(worker_id=worker, assignment_id=a.assignment_id,
                                               results=[{'index': 0, 'text': 'prints one'}], execution_time_ms=10)
    with factory() as db:
        complete_task(db, a.task_id, complete_payload)
    with factory() as db:
        complete_task(db, a.task_id, complete_payload)
        assert db.get(Worker, worker).active_tasks == 1
    assert claim('gemma3:12b') is None
    with factory.begin() as db:
        db.get(Task, b.task_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with factory() as db:
        assert recover_expired(db, SETTINGS) == 1
    retry = claim('qwen2.5-coder:3b')
    assert retry and retry.assignment_id != b.assignment_id
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            complete_task(db, b.task_id, TaskCompleteRequest(worker_id=worker, assignment_id=b.assignment_id,
                            results=[{'index': 0, 'text': 'stale'}], execution_time_ms=10))
        assert exc.value.status_code == 409
