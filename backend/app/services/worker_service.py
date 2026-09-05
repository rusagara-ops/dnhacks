from datetime import timedelta
from sqlalchemy import func, select
from app.models import Worker
from app.schemas.worker import WorkerRegisterRequest, WorkerResponse


def describe_worker(worker, now, timeout):
    # Presence is derived, so a read never mutates worker or future task state.
    status = 'OFFLINE' if now - worker.last_heartbeat > timedelta(seconds=timeout) else (
        'BUSY' if worker.active_tasks else 'AVAILABLE'
    )
    fields = {name: getattr(worker, name) for name in WorkerResponse.model_fields if name != 'status'}
    return WorkerResponse(**fields, status=status)


def register_worker(db, payload: WorkerRegisterRequest):
    worker = Worker(**payload.model_dump())
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def list_workers(db, timeout, limit, offset):
    now = db.scalar(select(func.clock_timestamp()))
    workers = db.scalars(select(Worker).order_by(Worker.created_at.desc(), Worker.id).limit(limit).offset(offset))
    return [describe_worker(worker, now, timeout) for worker in workers]
