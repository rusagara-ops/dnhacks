from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import func, select, or_, and_
from sqlalchemy.orm import aliased
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
    if payload.device_id is not None:
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(payload.device_id)))))
        existing = db.scalar(select(Worker).where(Worker.device_id == payload.device_id).with_for_update())
        if existing and existing.active_tasks and (existing.models != values['models'] or
                existing.model_id != payload.model_id or existing.model_revision != payload.model_revision):
            raise HTTPException(409, 'Drain active assignments before changing registered models')
    # Keep a location saved through the map when an older worker restarts.
    # Explicit null still clears it; explicit startup coordinates still update it.
    if 'location' not in payload.model_fields_set:
        values.pop('location', None)
    if payload.device_id is None:
        # Older clients have no installation ID. Serialize exact legacy-identity
        # retries and reuse their latest row without merging distinct modern devices.
        key = f'legacy-worker:{payload.hostname}:{payload.name}:{payload.model_id}:{payload.model_revision}'
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
        worker = db.scalar(select(Worker).where(
            Worker.device_id.is_(None), Worker.hostname == payload.hostname,
            Worker.name == payload.name, Worker.model_id == payload.model_id,
            Worker.model_revision == payload.model_revision,
        ).order_by(Worker.created_at.desc(), Worker.id).limit(1).with_for_update())
        if worker is None:
            worker = Worker(**values)
            db.add(worker)
        else:
            for name, value in values.items():
                setattr(worker, name, value)
            worker.last_heartbeat = db.scalar(select(func.clock_timestamp()))
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
    worker = db.get(Worker, worker_id)
    db.refresh(worker)  # The upsert bypasses an instance already loaded for the reconnect check.
    return worker


def update_location(db, worker_id, location, timeout):
    from fastapi import HTTPException
    with db.begin():
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        worker.location = location.model_dump() if location is not None else None
        db.flush()
        now = db.scalar(select(func.clock_timestamp()))
        return describe_worker(worker, now, timeout)


def list_workers(db, timeout, limit, offset, include_history=False):
    now = db.scalar(select(func.clock_timestamp()))
    query = visible_workers(now, timeout, include_history)
    workers = db.scalars(query.order_by(Worker.created_at.desc(), Worker.id).limit(limit).offset(offset))
    return [describe_worker(worker, now, timeout) for worker in workers]


def visible_workers(now, timeout, include_history=False):
    query = select(Worker)
    if not include_history:
        newer = aliased(Worker)
        replacement = select(newer.id).where(
            newer.hostname == Worker.hostname,
            newer.id != Worker.id,
            or_(newer.device_id.is_not(None),
                newer.created_at > Worker.created_at,
                and_(newer.created_at == Worker.created_at, newer.id > Worker.id)),
        ).exists()
        # Keep real device identities separate, even when hostnames match.
        # Suppress only superseded OFFLINE legacy rows; their history remains queryable.
        query = query.where(or_(Worker.device_id.is_not(None),
            Worker.last_heartbeat >= now - timedelta(seconds=timeout), ~replacement))
    return query
