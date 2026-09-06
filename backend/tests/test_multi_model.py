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
        w.models = [{'model_id': m, 'model_revision': 'v1', 'supported_tasks': ['coding-assistance']} for m in ['gemma', 'qwen']]
        w.model_id, w.model_revision = 'gemma', 'v1'
        w.supported_tasks = ['coding-assistance']
    for model in ['gemma', 'qwen', 'qwen']:
        with factory() as db:
            create_job(db, JobCreateRequest(task_type='coding-assistance', inputs=['print(1)'], model_id=model))
    def claim(model):
        with factory() as db:
            return get_next_task(db, worker, SETTINGS, model).task
    a, b = claim('gemma'), claim('qwen')
    assert a and b and a.task_id != b.task_id
    assert claim('qwen').assignment_id == b.assignment_id
    with factory() as db:
        assert db.get(Worker, worker).active_tasks == 2
        complete_payload = TaskCompleteRequest(worker_id=worker, assignment_id=a.assignment_id,
                                               results=[{'index': 0, 'text': 'prints one'}], execution_time_ms=10)
    with factory() as db:
        complete_task(db, a.task_id, complete_payload)
    with factory() as db:
        complete_task(db, a.task_id, complete_payload)
        assert db.get(Worker, worker).active_tasks == 1
    assert claim('gemma') is None
    with factory.begin() as db:
        db.get(Task, b.task_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with factory() as db:
        assert recover_expired(db, SETTINGS) == 1
    retry = claim('qwen')
    assert retry and retry.assignment_id != b.assignment_id
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            complete_task(db, b.task_id, TaskCompleteRequest(worker_id=worker, assignment_id=b.assignment_id,
                            results=[{'index': 0, 'text': 'stale'}], execution_time_ms=10))
        assert exc.value.status_code == 409
