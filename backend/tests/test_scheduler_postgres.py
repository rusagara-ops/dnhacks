"""Real independent-connection race tests; only generated temporary schemas are changed."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from app.core.config import Settings
from app.db.database import Base, make_engine
from app.models import Worker, Job, Task
from app.schemas.job import JobCreateRequest
from app.services.job_service import create_job
from app.services.scheduler import get_next_task

SETTINGS=Settings(_env_file=None,database_url=None,inference_model_id='test/model',inference_model_revision='test-revision',worker_timeout_seconds=300)


@pytest.fixture
def factory():
    url=os.environ.get('TEST_DATABASE_URL')
    if not url: pytest.skip('TEST_DATABASE_URL not set')
    engine=make_engine(url)
    schema='test_scheduler_'+uuid4().hex
    mapped=engine.execution_options(schema_translate_map={'coordinator':schema})
    try:
        with engine.begin() as c: c.execute(text(f'CREATE SCHEMA {schema}'))
        Base.metadata.create_all(mapped)
        yield sessionmaker(mapped,expire_on_commit=False)
    finally:
        with engine.begin() as c: c.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        engine.dispose()


def seed(factory,count=1,model='test/model',stale=False):
    with factory.begin() as db:
        workers=[Worker(name='test',hostname='test',cpu='test',cpu_cores=1,ram_gb=1,
                        supported_tasks=['sentiment-classification'],model_id=model,model_revision='test-revision',
                        last_heartbeat=datetime.now(timezone.utc)-timedelta(seconds=600 if stale else 0)) for _ in range(count)]
        db.add_all(workers); db.flush()
        return [w.id for w in workers]


def job(factory,inputs=25,model='test/model'):
    with factory() as db:
        return create_job(db,JobCreateRequest(task_type='sentiment-classification',inputs=['test']*inputs),model,'test-revision').id


def claim(factory,worker):
    with factory() as db: return get_next_task(db,worker,SETTINGS).task


def race(factory,workers):
    barrier=Barrier(len(workers))
    def run(w):
        barrier.wait(timeout=10)
        return claim(factory,w)
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        return list(pool.map(run,workers))


def test_two_workers_one_task(factory):
    workers=seed(factory,2); jid=job(factory)
    results=race(factory,workers)
    assert sum(r is not None for r in results)==1
    with factory() as db:
        task=db.scalar(select(Task).where(Task.job_id==jid))
        assert task.attempt_count==1 and task.status=='ASSIGNED'
        assert db.get(Job,jid).status=='RUNNING'
        assert db.get(Job,jid).started_at is not None


def test_same_worker_duplicate_pull_returns_same_assignment(factory):
    worker=seed(factory)[0]; job(factory,50)
    results=race(factory,[worker,worker])
    assert results[0].assignment_id==results[1].assignment_id
    with factory() as db:
        assert len(list(db.scalars(select(Task).where(Task.status=='ASSIGNED'))))==1
        # A lagging heartbeat must not allow a second assignment.
        db.get(Worker,worker).active_tasks=0; db.commit()
    assert claim(factory,worker).assignment_id==results[0].assignment_id


def test_two_workers_two_tasks(factory):
    workers=seed(factory,2); job(factory,50)
    results=race(factory,workers)
    assert len({r.task_id for r in results})==2
    assert len({r.assignment_id for r in results})==2
    assert all(r.model_id=='test/model' and r.lease_expires_at is not None for r in results)


def test_filtering_and_expiry(factory):
    worker=seed(factory)[0]
    job(factory,model='incompatible/model')
    good=job(factory)
    result=claim(factory,worker)
    assert result.job_id==good
    with factory.begin() as db:
        db.get(Task,result.task_id).lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    with pytest.raises(HTTPException) as e: claim(factory,worker)
    assert e.value.status_code==409


def test_offline_unknown_unconfigured_and_empty(factory):
    worker=seed(factory,stale=True)[0]
    with pytest.raises(HTTPException) as e: claim(factory,worker)
    assert e.value.status_code==409
    with pytest.raises(HTTPException) as e: claim(factory,uuid4())
    assert e.value.status_code==404
    fresh=seed(factory)[0]
    assert claim(factory,fresh) is None
    with factory() as db:
        with pytest.raises(HTTPException) as e:
            get_next_task(db,fresh,Settings(_env_file=None,database_url=None))
        assert e.value.status_code==503
