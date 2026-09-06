from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, update, or_

from app.services.recovery import recover_expired
from app.models import Job, Task, Worker
from app.schemas.task import NextTaskResponse, TaskAssignment


def assignment_response(task, job):
    return NextTaskResponse(task=TaskAssignment(
        task_id=task.id, job_id=job.id, assignment_id=task.assignment_id,
        lease_expires_at=task.lease_expires_at, task_type=job.task_type,
        model_id=job.model_id, model_revision=job.model_revision,
        inputs=task.payload['inputs'], instruction=task.payload.get('instruction'),
    ))


def get_next_task(db, worker_id, settings, model_id=None):
    recover_expired(db, settings)
    with db.begin():
        # Lock worker first everywhere that modifies assignment ownership.
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        now = db.scalar(select(func.clock_timestamp()))
        if now - worker.last_heartbeat > timedelta(seconds=settings.worker_timeout_seconds):
            raise HTTPException(409, 'Worker is offline; send a heartbeat first')
        slot = model_id if worker.models else ''
        inventory = worker.models or [{'model_id': worker.model_id, 'model_revision': worker.model_revision, 'supported_tasks': worker.supported_tasks}]
        selected = next((m for m in inventory if m['model_id'] == (model_id or worker.model_id)), None)
        if selected is None:
            raise HTTPException(422, 'Model is not registered on this worker')
        if worker.models and model_id is None:
            slot = selected['model_id']
        active = db.scalar(select(Task).where(
            Task.assigned_worker_id == worker_id, Task.model_slot == slot, Task.status.in_(['ASSIGNED', 'RUNNING'])
        ).with_for_update())
        if active:
            if active.lease_expires_at is None or active.lease_expires_at <= now:
                raise HTTPException(409, 'Assignment expired; retry after recovery')
            # A lost HTTP response can be retried without consuming another attempt.
            return assignment_response(active, db.get(Job, active.job_id))
        if worker.models and worker.active_tasks >= len(worker.models):
            return NextTaskResponse(task=None)
        if not settings.inference_model_id or not settings.inference_model_revision:
            raise HTTPException(503, 'Inference model and revision are not configured')
        if worker.active_tasks and not worker.models:
            return NextTaskResponse(task=None)
        if not worker.model_id or not worker.model_revision:
            raise HTTPException(409, 'Register with a loaded model ID and revision first')
        task = db.scalar(select(Task).join(Job, Task.job_id == Job.id).where(
            Task.status == 'QUEUED', Task.attempt_count < 3,
            Job.status.in_(['QUEUED', 'RUNNING']),
            or_(Job.target_worker_id.is_(None), Job.target_worker_id == worker_id),
            Job.task_type.in_(selected['supported_tasks']),
            Job.model_id == selected['model_id'], Job.model_revision == selected['model_revision'],
        ).order_by(Task.created_at, Task.start_index, Task.id)
            .with_for_update(skip_locked=True, of=Task).limit(1))
        if task is None:
            return NextTaskResponse(task=None)
        task.started_at = now
        task.status = 'ASSIGNED'
        task.assigned_worker_id = worker_id
        task.assignment_id = uuid4()
        task.lease_expires_at = now + timedelta(seconds=settings.task_lease_seconds)
        task.attempt_count += 1
        task.model_slot = slot
        worker.active_tasks += 1
        # Conditional SQL update avoids resetting an already-running job's start time.
        db.execute(update(Job).where(Job.id == task.job_id, Job.status == 'QUEUED')
                   .values(status='RUNNING', started_at=now))
        db.flush()
        return assignment_response(task, db.get(Job, task.job_id))
