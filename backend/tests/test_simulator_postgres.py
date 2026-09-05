"""Actual HTTP server and worker subprocesses backed by an isolated PostgreSQL schema."""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from test_scheduler_postgres import factory
from app.core.config import Settings
from app.db.database import get_db
from app.main import create_app
from app.models import Task, Worker
from scripts.simulated_worker import MODEL_ID, MODEL_REVISION


@pytest.fixture
def server(factory):
    settings=Settings(_env_file=None,database_url=None,api_token='sim-test',
        inference_model_id=MODEL_ID,inference_model_revision=MODEL_REVISION,
        heartbeat_interval_seconds=1,worker_timeout_seconds=3)
    app=create_app(settings)
    def db():
        with factory() as session: yield session
    app.dependency_overrides[get_db]=db
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    service=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=service.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not service.started:
            assert thread.is_alive() and time.monotonic()<deadline
            time.sleep(0.02)
        with httpx.Client(base_url=url,headers={'Authorization':'Bearer sim-test'},timeout=20) as client:
            yield url,client
    finally:
        service.should_exit=True;thread.join(timeout=10);sock.close()
        assert not thread.is_alive()


def launch(url,*args):
    env={k:v for k,v in os.environ.items() if k not in ['DATABASE_URL','TEST_DATABASE_URL']}
    env['API_TOKEN']='sim-test'
    return subprocess.Popen([sys.executable,'-m','scripts.simulated_worker','--url',url,
        '--poll-seconds','0.2','--idle-timeout','8',*args],cwd=Path(__file__).resolve().parents[1],env=env,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def test_two_worker_processes_and_stats(server,factory):
    url,c=server
    assert c.get('/api/stats',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert all(v==0 for v in c.get('/api/stats').json().values())
    r=c.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':['synthetic']*100});assert r.status_code==201;jid=r.json()['job_id']
    workers=[launch(url,'--name',f'sim-{i}','--max-tasks','2','--delay','2') for i in range(2)]
    try:
        for worker in workers:
            output=worker.communicate(timeout=60)[0]
            assert worker.returncode==0,output
        result=c.get(f'/api/jobs/{jid}/results').json()
        assert result['status']=='COMPLETED' and len(result['results'])==100
        assert [p['index'] for p in result['results']]==list(range(100))
        stats=c.get('/api/stats').json()
        assert stats['jobs_completed']==1 and stats['jobs_running']==0
        assert stats['tasks_completed']==4 and stats['total_inferences']==100
        with factory() as db:
            assert len(set(db.scalars(select(Task.assigned_worker_id))))==2
    finally:
        for worker in workers:stop(worker)


def test_crashed_process_recovers_without_manual_database_edits(server,factory):
    url,c=server
    r=c.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':['synthetic']});jid=r.json()['job_id']
    crashed=launch(url,'--name','crashed','--crash-after-claim')
    survivor=None
    try:
        output=crashed.communicate(timeout=30)[0];assert crashed.returncode==17,output
        survivor=launch(url,'--name','survivor','--max-tasks','1','--delay','1')
        output=survivor.communicate(timeout=60)[0];assert survivor.returncode==0,output
        assert c.get(f'/api/jobs/{jid}/results').json()['status']=='COMPLETED'
        with factory() as db:
            task=db.scalar(select(Task));assert task.attempt_count==2
            assert db.get(Worker,task.assigned_worker_id).name=='survivor'
        assert c.get('/api/stats').json()['total_inferences']==1
    finally:
        stop(crashed)
        if survivor:stop(survivor)


def test_failure_mode_exhausts_retries(server):
    url,c=server
    jid=c.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':['synthetic']}).json()['job_id']
    worker=launch(url,'--fail-tasks','--max-tasks','3','--delay','0.1')
    try:
        output=worker.communicate(timeout=60)[0];assert worker.returncode==0,output
        result=c.get(f'/api/jobs/{jid}/results').json()
        assert result['status']=='FAILED' and result['failed_inputs']==1 and result['results']==[]
        stats=c.get('/api/stats').json()
        assert stats['jobs_failed']==1 and stats['total_inferences']==0
    finally:stop(worker)
