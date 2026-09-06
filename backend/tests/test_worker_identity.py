from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy import select,func
from test_scheduler_postgres import factory,job,claim
from app.models import Worker
from app.schemas.worker import WorkerRegisterRequest
from app.services.worker_service import register_worker
from app.api.activity import activity


def payload(device):
    return WorkerRegisterRequest(device_id=device,name='Reconnect-Test',hostname='test-host',cpu='test',cpu_cores=1,
        ram_gb=8,supported_tasks=['sentiment-classification'],model_id='test/model',model_revision='test-revision')


def test_concurrent_reconnect_reuses_worker(factory):
    device=uuid4();barrier=Barrier(2)
    def register(_):
        barrier.wait(timeout=10)
        with factory() as db:return register_worker(db,payload(device)).id
    with ThreadPoolExecutor(2) as pool: ids=list(pool.map(register,range(2)))
    assert ids[0]==ids[1]
    with factory() as db: assert db.scalar(select(func.count()).select_from(Worker))==1
    jid=job(factory);assigned=claim(factory,ids[0])
    with factory() as db: assert register_worker(db,payload(device)).active_tasks==1
    again=claim(factory,ids[0]);assert again.assignment_id==assigned.assignment_id
    with factory() as db:
        data=activity(db)
        assert data['active_tasks'][0]['worker_id']==ids[0]
        assert data['active_tasks'][0]['job_id']==jid
        assert data['active_tasks'][0]['elapsed_seconds']>=0
    from test_lifecycle_postgres import finish
    assert finish(factory,ids[0],assigned)=='completed'
    with factory() as db:
        data=activity(db)
        metrics=data['worker_metrics'][0]
        assert metrics['completed_tasks']==1 and metrics['completed_inputs']==25
        assert metrics['average_execution_ms']==12
        assert data['worker_task_types']==[{'worker_id':ids[0], 'task_type':'sentiment-classification', 'completed_tasks':1}]


def test_same_name_different_devices_stay_separate(factory):
    with factory() as db:a=register_worker(db,payload(uuid4())).id
    with factory() as db:b=register_worker(db,payload(uuid4())).id
    assert a!=b


def test_legacy_retry_and_default_listing(factory):
    from datetime import datetime,timedelta,timezone
    from app.services.worker_service import list_workers
    legacy=payload(None)
    with factory() as db: first=register_worker(db,legacy).id
    with factory() as db: assert register_worker(db,legacy).id==first
    with factory() as db: modern=register_worker(db,payload(uuid4())).id
    with factory.begin() as db:db.get(Worker,first).last_heartbeat=datetime.now(timezone.utc)-timedelta(seconds=60)
    with factory() as db:
        assert [w.id for w in list_workers(db,15,100,0)]==[modern]
        assert len(list_workers(db,15,100,0,include_history=True))==2


def test_modern_devices_with_same_hostname_are_not_hidden(factory):
    from app.services.worker_service import list_workers
    with factory() as db:register_worker(db,payload(uuid4()))
    with factory() as db:register_worker(db,payload(uuid4()))
    with factory() as db:assert len(list_workers(db,15,100,0))==2
