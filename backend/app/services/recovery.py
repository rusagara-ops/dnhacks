from datetime import timedelta
from sqlalchemy import select, func, or_
from app.models import Worker, Task
from app.services.task_service import ACTIVE, release_task


def recover_expired(db, settings):
    with db.begin():
        now = db.scalar(select(func.clock_timestamp()))
        candidates = list(db.scalars(select(Worker.id).join(Task, Task.assigned_worker_id == Worker.id).where(
            Task.status.in_(ACTIVE), or_(Task.lease_expires_at <= now,
                                        Worker.last_heartbeat < now - timedelta(seconds=settings.worker_timeout_seconds))
        ).order_by(Worker.id).limit(100)))
    recovered = 0
    # One worker/task/job per transaction keeps lock ordering simple across concurrent sweepers.
    for worker_id in candidates:
        with db.begin():
            worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update(skip_locked=True))
            if worker is None:
                continue
            task = db.scalar(select(Task).where(Task.assigned_worker_id == worker_id, Task.status.in_(ACTIVE))
                             .with_for_update(skip_locked=True))
            if task is None:
                continue
            now = db.scalar(select(func.clock_timestamp()))
            if task.lease_expires_at <= now or worker.last_heartbeat < now - timedelta(seconds=settings.worker_timeout_seconds):
                release_task(db, worker, task, now, 'ASSIGNMENT_EXPIRED', 'Lease expired or worker heartbeat timed out')
                recovered += 1
    return recovered
