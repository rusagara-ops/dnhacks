"""PostgreSQL verification in a temporary schema, rolled back after the suite.

Set TEST_DATABASE_URL to opt in. Existing application tables are never modified.
"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.database import make_engine
from app.main import create_app
from app.models import Account, Job, Task, Worker
from app.schemas.job import JobCreateRequest
from app.services.job_service import create_job


@pytest.fixture(scope='module')
def connection():
    url=os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL not set')
    engine=make_engine(url)
    schema='test_jobs_'+uuid4().hex
    with engine.connect() as conn:
        transaction=conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA {schema}'))
            mapped=conn.execution_options(schema_translate_map={'coordinator':schema})
            Account.__table__.create(mapped)
            Worker.__table__.create(mapped)
            path=Path(__file__).resolve().parents[1]/'migrations/versions/1781ed678f6b_add_jobs_and_queued_tasks.py'
            spec=importlib.util.spec_from_file_location('job_migration_test',path)
            migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
            migration.op=SimpleNamespace(execute=lambda sql: conn.execute(text(sql.replace('coordinator.',schema+'.'))))
            migration.upgrade()
            conn.execute(text(f'ALTER TABLE {schema}.jobs ADD COLUMN model_id TEXT, ADD COLUMN model_revision TEXT'))
            conn.execute(text(f'ALTER TABLE {schema}.jobs ADD COLUMN target_worker_id UUID REFERENCES {schema}.workers(id)'))
            conn.execute(text(f'ALTER TABLE {schema}.jobs ADD COLUMN owner_account_id UUID REFERENCES {schema}.accounts(id)'))
            conn.execute(text(f'ALTER TABLE {schema}.tasks ADD COLUMN last_error JSONB'))
            conn.execute(text(f"ALTER TABLE {schema}.tasks ADD COLUMN model_slot TEXT NOT NULL DEFAULT ''"))
            yield mapped
        finally:
            transaction.rollback()
    engine.dispose()


def sessions(connection):
    return Session(bind=connection,expire_on_commit=False,join_transaction_mode='create_savepoint')


def test_creation_read_restart_and_pagination(connection):
    settings=Settings(_env_file=None,database_url=None,api_token='test')
    with TestClient(create_app(settings)) as client:
        client.app.state.sessions=lambda: sessions(connection)
        client.headers['Authorization']='Bearer test'
        inputs=[f' original input {i} ' for i in range(100)]
        r=client.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':inputs})
        assert r.status_code==201, r.text
        assert r.json()['total_tasks']==4
        jid=r.json()['job_id']
        assert r.headers['location']==f'/api/jobs/{jid}'
        with sessions(connection) as db:
            from uuid import UUID
            tasks=list(db.scalars(select(Task).where(Task.job_id==UUID(jid)).order_by(Task.start_index)))
            assert len(tasks)==4
            assert all(t.status=='QUEUED' and t.attempt_count==0 and t.assignment_id is None for t in tasks)
            assert [i for t in tasks for i in t.payload['inputs']]==[{'index':i,'text':v} for i,v in enumerate(inputs)]
        with sessions(connection) as db:
            before=db.scalar(select(func.count()).select_from(Job))
        assert client.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':[]}).status_code==422
        with sessions(connection) as db:
            assert db.scalar(select(func.count()).select_from(Job))==before
    with TestClient(create_app(settings)) as client:
        client.app.state.sessions=lambda: sessions(connection)
        client.headers['Authorization']='Bearer test'
        response=client.get(f'/api/jobs/{jid}')
        assert response.status_code==200
        assert response.json()['status']=='QUEUED'
        assert response.json()['progress_percentage']==0
        assert response.json()['total_inputs']==100
        assert response.json()['started_at'] is None
        assert len(client.get('/api/jobs?limit=1').json())==1
        assert client.get('/api/jobs?offset=10000').json()==[]


def test_mid_creation_failure_rolls_back_entire_job(connection):
    with sessions(connection) as db:
        jobs_before=db.scalar(select(func.count()).select_from(Job))
        tasks_before=db.scalar(select(func.count()).select_from(Task))
    def fail_second_chunk(mapper, conn, target):
        if target.start_index==25:
            raise RuntimeError('injected task insert failure')
    event.listen(Task,'before_insert',fail_second_chunk)
    try:
        with sessions(connection) as db:
            with pytest.raises(RuntimeError,match='injected'):
                create_job(db,JobCreateRequest(task_type='sentiment-classification',inputs=['test']*100))
    finally:
        event.remove(Task,'before_insert',fail_second_chunk)
    with sessions(connection) as db:
        assert db.scalar(select(func.count()).select_from(Job))==jobs_before
        assert db.scalar(select(func.count()).select_from(Task))==tasks_before


def test_schema_constraints_and_rls(connection):
    schema=connection.get_execution_options()['schema_translate_map']['coordinator']
    for name in ['jobs','tasks']:
        assert connection.scalar(text('SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(:table)'),{'table':schema+'.'+name})
    from sqlalchemy.exc import IntegrityError
    with sessions(connection) as db:
        with pytest.raises(IntegrityError):
            with db.begin():
                db.add(Job(task_type='sentiment-classification',optimization='fastest',total_inputs=1,total_tasks=0))
                db.flush()
