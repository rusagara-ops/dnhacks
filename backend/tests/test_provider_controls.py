from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.models import Worker, Task, ExecutionAttempt
from app.schemas.provider import ProviderPolicyUpdate, AvailabilityWindow, ALL_TASKS
from app.schemas.task import TaskCompleteRequest, TaskFailRequest
from app.services.provider import set_policy, admission_reasons, provider_workers
from app.services.scheduler import get_next_task
from app.services.task_service import complete_task, fail_task
from app.services.recovery import recover_expired
from app.core.security import Principal
from test_scheduler_postgres import factory, seed, job, SETTINGS


def policy(**changes):
    return ProviderPolicyUpdate(**(dict(sharing_enabled=True, allowed_task_types=ALL_TASKS,
        max_concurrent_tasks=2, min_ram_available_gb=0, availability=[]) | changes))


def change(factory, wid, **changes):
    with factory() as db:
        return set_policy(db, wid, policy(**changes))


def claim(factory, wid):
    with factory() as db:
        return get_next_task(db, wid, SETTINGS).task


def completion(wid, task):
    return TaskCompleteRequest(worker_id=wid, assignment_id=task.assignment_id,
        results=[dict(index=i.index, label='POSITIVE', score=0.9) for i in task.inputs], execution_time_ms=25)


def test_pause_drains_active_task_and_resume_accepts_next(factory):
    wid = seed(factory)[0]
    job(factory, 26)
    active = claim(factory, wid)
    change(factory, wid, sharing_enabled=False)
    assert claim(factory, wid).assignment_id == active.assignment_id
    with factory() as db:
        complete_task(db, active.task_id, completion(wid, active))
    assert claim(factory, wid) is None
    change(factory, wid)
    assert claim(factory, wid).task_id != active.task_id


def test_allowed_workloads_and_memory_unknown_block_new_assignment(factory):
    wid = seed(factory)[0]
    job(factory)
    change(factory, wid, allowed_task_types=['coding-assistance'])
    assert claim(factory, wid) is None
    change(factory, wid, min_ram_available_gb=0.5)
    assert claim(factory, wid) is None
    with factory.begin() as db:
        db.get(Worker, wid).ram_available_gb = 0.6
    assert claim(factory, wid) is not None


def test_utc_schedule_has_inclusive_start_exclusive_end_and_valid_days():
    worker = SimpleNamespace(owner_account_id=None, ram_available_gb=1)
    schedule = [dict(days=[0], start_minute=9*60, end_minute=10*60)]
    p = SimpleNamespace(**policy(availability=schedule).model_dump())
    assert admission_reasons(worker, p, datetime(2026, 9, 7, 9, tzinfo=timezone.utc)) == []
    assert 'OUTSIDE_PROVIDER_SCHEDULE' in admission_reasons(worker, p, datetime(2026, 9, 7, 10, tzinfo=timezone.utc))
    assert 'OUTSIDE_PROVIDER_SCHEDULE' in admission_reasons(worker, p, datetime(2026, 9, 8, 9, tzinfo=timezone.utc))
    for invalid in (dict(days=[7], start_minute=0, end_minute=60),
                    dict(days=[0, 0], start_minute=0, end_minute=60),
                    dict(days=[0], start_minute=1380, end_minute=60)):
        with pytest.raises(ValidationError):
            AvailabilityWindow(**invalid)


def test_ownership_defaults_pause_and_concurrency_limit():
    now = datetime.now(timezone.utc)
    worker = SimpleNamespace(owner_account_id='owned', ram_available_gb=1)
    assert 'SHARING_PAUSED' in admission_reasons(worker, None, now)
    p = SimpleNamespace(**policy(max_concurrent_tasks=1).model_dump())
    assert 'PROVIDER_CONCURRENCY_LIMIT' in admission_reasons(worker, p, now, active_count=1)
    assert admission_reasons(worker, p, now, active_count=0) == []


def test_attempt_history_retains_failure_and_expiry_after_reassignment(factory):
    first, second = seed(factory, 2)
    job(factory, 1)
    a = claim(factory, first)
    with factory() as db:
        fail_task(db, a.task_id, TaskFailRequest(worker_id=first, assignment_id=a.assignment_id,
            error={'code': 'INFERENCE_FAILED', 'message': 'test'}))
    b = claim(factory, second)
    with factory.begin() as db:
        db.get(Task, b.task_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with factory() as db:
        assert recover_expired(db, SETTINGS) == 1
    c = claim(factory, second)
    with factory() as db:
        complete_task(db, c.task_id, completion(second, c))
    with factory() as db:
        complete_task(db, c.task_id, completion(second, c))
    with factory() as db:
        attempts = db.scalars(select(ExecutionAttempt)).all()
        assert len(attempts) == 3
        assert {a.status for a in attempts} == {'FAILED', 'EXPIRED', 'COMPLETED'}
        data = provider_workers(db, Principal(None, 'demo', 'admin', 'demo', 'demo'), SETTINGS)
        metrics = {i['worker_id']: i['reliability'] for i in data['items']}
        assert metrics[first]['failed_attempts'] == 1
        assert metrics[second]['expired_attempts'] == 1
        assert metrics[second]['completed_tasks'] == 1
        assert metrics[second]['average_reported_execution_ms'] == 25
