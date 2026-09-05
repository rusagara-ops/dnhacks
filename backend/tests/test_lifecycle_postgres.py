from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from test_scheduler_postgres import factory, seed, job, claim, SETTINGS
from app.models import Job, Task, TaskResult, Worker
from app.schemas.task import TaskCompleteRequest, TaskFailRequest
from app.schemas.worker import HeartbeatRequest
from app.services.task_service import complete_task, fail_task, job_results, renew_heartbeat
from app.services.recovery import recover_expired


def completion(worker, assignment):
    return TaskCompleteRequest(worker_id=worker, assignment_id=assignment.assignment_id,
        results=[{'index':i.index,'label':'POSITIVE','score':0.9} for i in assignment.inputs], execution_time_ms=12)


def finish(factory, worker, assignment):
    with factory() as db: return complete_task(db,assignment.task_id,completion(worker,assignment)).status


def results(factory, jid):
    with factory() as db: return job_results(db,jid)


def test_duplicate_completion_race(factory):
    w=seed(factory)[0];jid=job(factory);a=claim(factory,w)
    barrier=Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return finish(factory,w,a)
    with ThreadPoolExecutor(2) as pool: statuses=list(pool.map(run,range(2)))
    assert sorted(statuses)==['already_completed','completed']
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TaskResult))==1
        j=db.get(Job,jid);assert j.completed_tasks==1 and j.status=='COMPLETED'
        assert db.get(Worker,w).active_tasks==0


def test_parallel_completions_keep_counts_and_order(factory):
    workers=seed(factory,2);jid=job(factory,26);a=claim(factory,workers[0]);b=claim(factory,workers[1])
    barrier=Barrier(2)
    def run(pair):
        barrier.wait(timeout=10)
        return finish(factory,*pair)
    with ThreadPoolExecutor(2) as pool: assert list(pool.map(run,zip(workers,[a,b])))==['completed','completed']
    r=results(factory,jid)
    assert r.status=='COMPLETED' and r.is_final and r.completed_inputs==26
    assert [p.index for p in r.results]==list(range(26))


def test_expiry_reassignment_rejects_old_worker(factory):
    w1,w2=seed(factory,2);jid=job(factory);old=claim(factory,w1)
    with factory.begin() as db: db.get(Task,old.task_id).lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    new=claim(factory,w2)
    assert new.task_id==old.task_id and new.assignment_id!=old.assignment_id
    with pytest.raises(HTTPException) as e: finish(factory,w1,old)
    assert e.value.status_code==409
    assert finish(factory,w2,new)=='completed'
    with factory() as db: assert db.get(Task,new.task_id).attempt_count==2


def test_three_failures_and_partial_results(factory):
    w1,w2=seed(factory,2);jid=job(factory,26);good=claim(factory,w1);bad=claim(factory,w2)
    for attempt in range(3):
        payload=TaskFailRequest(worker_id=w2,assignment_id=bad.assignment_id,error={'code':'INFERENCE_ERROR','message':'test error'})
        with factory() as db: status=fail_task(db,bad.task_id,payload).status
        assert status==('failed' if attempt==2 else 'requeued')
        with factory() as db: assert fail_task(db,bad.task_id,payload).status=='already_failed'
        if attempt<2: bad=claim(factory,w2)
    interim=results(factory,jid)
    assert interim.status=='RUNNING' and not interim.is_final and interim.failed_inputs==1
    finish(factory,w1,good)
    r=results(factory,jid)
    assert r.status=='FAILED' and r.is_final and r.completed_inputs==25 and r.failed_inputs==1
    assert len(r.results)==25 and len(r.failed_tasks)==1
    with factory() as db:
        j=db.get(Job,jid);assert j.completed_tasks==1 and j.failed_tasks==1
        assert db.get(Task,bad.task_id).attempt_count==3


def test_heartbeat_renews_only_current_assignment(factory):
    w=seed(factory)[0];job(factory);a=claim(factory,w)
    with factory.begin() as db:
        db.get(Task,a.task_id).lease_expires_at=datetime.now(timezone.utc)+timedelta(seconds=30)
    payload=HeartbeatRequest(cpu_utilization=10,memory_utilization=20,active_tasks=1,task_id=a.task_id,assignment_id=a.assignment_id)
    with factory() as db: expiry=renew_heartbeat(db,w,payload,SETTINGS)
    assert expiry>datetime.now(timezone.utc)+timedelta(seconds=200)
    payload.assignment_id=uuid4()
    with factory() as db:
        with pytest.raises(HTTPException) as e: renew_heartbeat(db,w,payload,SETTINGS)
        assert e.value.status_code==409
    with factory() as db: assert db.get(Task,a.task_id).status=='RUNNING'


def test_wrong_indices_leave_task_active(factory):
    w=seed(factory)[0];jid=job(factory,1);a=claim(factory,w);p=completion(w,a);p.results[0].index=999
    with factory() as db:
        with pytest.raises(HTTPException) as e: complete_task(db,a.task_id,p)
        assert e.value.status_code==422
    with factory() as db:
        assert db.get(Task,a.task_id).status=='ASSIGNED'
        assert db.get(Job,jid).completed_tasks==0
        assert db.scalar(select(func.count()).select_from(TaskResult))==0


def test_offline_recovery_exhausts_attempts(factory):
    w=seed(factory)[0];jid=job(factory,1)
    for attempt in range(3):
        with factory.begin() as db: db.get(Worker,w).last_heartbeat=datetime.now(timezone.utc)
        a=claim(factory,w)
        with factory.begin() as db: db.get(Worker,w).last_heartbeat=datetime.now(timezone.utc)-timedelta(seconds=600)
        with factory() as db: assert recover_expired(db,SETTINGS)==1
        with factory() as db: assert recover_expired(db,SETTINGS)==0
    r=results(factory,jid)
    assert r.status=='FAILED' and r.failed_inputs==1 and r.completed_inputs==0


def test_result_insert_failure_rolls_back_completion(factory):
    from sqlalchemy import event
    w=seed(factory)[0];jid=job(factory,1);a=claim(factory,w)
    def fail_insert(mapper, connection, target):
        raise RuntimeError('injected result failure')
    event.listen(TaskResult,'before_insert',fail_insert)
    try:
        with pytest.raises(RuntimeError,match='injected'): finish(factory,w,a)
    finally:
        event.remove(TaskResult,'before_insert',fail_insert)
    with factory() as db:
        assert db.get(Task,a.task_id).status=='ASSIGNED'
        assert db.get(Job,jid).completed_tasks==0
        assert db.get(Worker,w).active_tasks==1
        assert db.scalar(select(func.count()).select_from(TaskResult))==0
    assert finish(factory,w,a)=='completed'
