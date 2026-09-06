from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from app.schemas.worker import HeartbeatRequest
from app.services.task_service import renew_heartbeat
from app.services.worker_service import list_workers
from app.models import Worker
from test_scheduler_postgres import factory, seed, SETTINGS


def test_heartbeat_persists_live_memory(factory):
    worker_id = seed(factory)[0]
    with factory.begin() as db:
        w=db.get(Worker,worker_id)
        w.ram_gb=24
        w.gpu='Apple M4 Pro'
        w.gpu_core_count=20
        w.gpu_memory_kind='unified'
    def beat(available):
        return HeartbeatRequest(cpu_utilization=30,memory_utilization=50,active_tasks=0,
                                ram_available_gb=available,gpu_model_memory_gb=8)
    with factory() as db: renew_heartbeat(db,worker_id,beat(12),SETTINGS)
    with factory() as db:
        w=list_workers(db,15,100,0)[0]
        assert w.ram_available_gb==12 and w.gpu_core_count==20 and w.gpu_model_memory_gb==8
        assert w.gpu_available_gb is None and w.gpu_memory_gb is None
    with factory() as db: renew_heartbeat(db,worker_id,beat(9),SETTINGS)
    with factory() as db: assert db.get(Worker,worker_id).ram_available_gb==9
    # Legacy workers remain supported; omitted measurements become unknown.
    with factory() as db:
        renew_heartbeat(db,worker_id,HeartbeatRequest(cpu_utilization=0,memory_utilization=0,active_tasks=0),SETTINGS)
    with factory() as db: assert db.get(Worker,worker_id).ram_available_gb is None


@pytest.mark.parametrize('value',[-1,float('inf'),float('nan')])
def test_invalid_available_memory(value):
    with pytest.raises(ValidationError):
        HeartbeatRequest(cpu_utilization=0,memory_utilization=0,active_tasks=0,ram_available_gb=value)


def test_impossible_memory_rolls_back(factory):
    from fastapi import HTTPException
    worker_id=seed(factory)[0]
    with factory() as db, pytest.raises(HTTPException) as exc:
        renew_heartbeat(db,worker_id,HeartbeatRequest(cpu_utilization=99,memory_utilization=99,
                         active_tasks=0,ram_available_gb=50),SETTINGS)
    assert exc.value.status_code==422
    with factory() as db: assert db.get(Worker,worker_id).cpu_utilization==0
