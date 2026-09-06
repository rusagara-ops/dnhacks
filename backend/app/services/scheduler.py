from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, update, or_

from app.services.recovery import recover_expired
from app.services.eligibility import eligibility_reasons
from app.core.model_registry import MODEL_REGISTRY
from app.models import Job, Task, Worker
from app.schemas.task import NextTaskResponse, TaskAssignment
from app.models.provider import ProviderPolicy, ExecutionAttempt
from app.services.provider import admission_reasons, describe_policy


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
        policy = db.get(ProviderPolicy, worker_id)
        active_count = db.scalar(select(func.count()).select_from(Task).where(
            Task.assigned_worker_id == worker_id, Task.status.in_(['ASSIGNED', 'RUNNING'])))
        if admission_reasons(worker, policy, now, active_count):
            return NextTaskResponse(task=None)
        if worker.models and worker.active_tasks >= len(worker.models):
            return NextTaskResponse(task=None)
        if not settings.inference_model_id or not settings.inference_model_revision:
            raise HTTPException(503, 'Inference model and revision are not configured')
        if worker.active_tasks and not worker.models:
            return NextTaskResponse(task=None)
        if not worker.model_id or not worker.model_revision:
            raise HTTPException(409, 'Register with a loaded model ID and revision first')
        spec = MODEL_REGISTRY.get(selected['model_id'])
        supported = [kind for kind in selected['supported_tasks'] if spec is None or kind in spec.task_types]
        supported = [kind for kind in supported if kind in describe_policy(policy, worker)['allowed_task_types']]
        if not supported:
            return NextTaskResponse(task=None)
        # The selected slot was checked under the worker lock above; another
        # model's active assignment must not mark this free slot busy.
        if eligibility_reasons(worker, selected['model_id'], selected['model_revision'],
                               supported[0],
                               now, settings.worker_timeout_seconds, active_model_ids=set()):
            return NextTaskResponse(task=None)
        task = db.scalar(select(Task).join(Job, Task.job_id == Job.id).where(
            Task.status == 'QUEUED', Task.attempt_count < 3,
            Job.status.in_(['QUEUED', 'RUNNING']),
            or_(Job.target_worker_id.is_(None), Job.target_worker_id == worker_id),
            # Unenrolled demo machines cannot receive paid/owned jobs.
            or_(Job.owner_account_id.is_(None), worker.owner_account_id is not None),
            or_(getattr(settings, 'auth_mode', 'demo') != 'controlled', Job.owner_account_id.is_not(None)),
            Job.task_type.in_(supported),
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
        db.add(ExecutionAttempt(assignment_id=task.assignment_id, task_id=task.id,
            worker_id=worker.id, status='ASSIGNED', started_at=now))
        worker.active_tasks += 1
        # Conditional SQL update avoids resetting an already-running job's start time.
        db.execute(update(Job).where(Job.id == task.job_id, Job.status == 'QUEUED')
                   .values(status='RUNNING', started_at=now))
        db.flush()
        return assignment_response(task, db.get(Job, task.job_id))
