from datetime import timedelta
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
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
    values = payload.model_dump()
    if payload.device_id is None:
        # Legacy clients keep their original registration behavior.
        worker = Worker(**values)
        db.add(worker)
        db.commit()
        db.refresh(worker)
        return worker
    # A unique device ID makes concurrent retries return the same worker row.
    # Preserve active assignments and counters during reconnects.
    statement = insert(Worker).values(**values)
    updates = {k: getattr(statement.excluded, k) for k in values if k != 'device_id'}
    updates.update(last_heartbeat=func.now(), updated_at=func.now())
    worker_id = db.scalar(statement.on_conflict_do_update(
        index_elements=[Worker.device_id], set_=updates).returning(Worker.id))
    db.commit()
    return db.get(Worker, worker_id)


def list_workers(db, timeout, limit, offset):
    now = db.scalar(select(func.clock_timestamp()))
    workers = db.scalars(select(Worker).order_by(Worker.created_at.desc(), Worker.id).limit(limit).offset(offset))
    return [describe_worker(worker, now, timeout) for worker in workers]
