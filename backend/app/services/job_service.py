from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import Job, Task, Worker, WorkRequest
from app.schemas.job import JobResponse

CHUNK_SIZE = 25


def split_into_tasks(inputs, chunk_size=CHUNK_SIZE):
    for start in range(0, len(inputs), chunk_size):
        chunk = inputs[start:start + chunk_size]
        yield {'start_index': start, 'input_count': len(chunk), 'payload': {
            'inputs': [{'index': start + offset, 'text': value} for offset, value in enumerate(chunk)]
        }}


def create_job(db, payload, model_id=None, model_revision=None, worker_timeout=15, owner_account_id=None):
    chunk_size = CHUNK_SIZE if payload.task_type == 'sentiment-classification' else 1
    request = None
    # The job and every chunk must become visible together, or not at all.
    with db.begin():
        if payload.work_request_id is not None:
            request = db.scalar(select(WorkRequest).where(
                WorkRequest.id == payload.work_request_id,
                WorkRequest.requester_account_id == owner_account_id,
            ).with_for_update())
            if request is None:
                raise HTTPException(404, 'Work request not found')
            if request.status != 'APPROVED':
                raise HTTPException(409, 'Work request must be approved before submitting a job')
            if request.task_type != payload.task_type:
                raise HTTPException(409, 'Job task does not match the approved work request')
            if payload.target_worker_id is not None and payload.target_worker_id != request.worker_id:
                raise HTTPException(409, 'Job worker does not match the approved work request')
            payload_target_worker_id = request.worker_id
        else:
            payload_target_worker_id = payload.target_worker_id
        if payload.model_id is not None:
            now = db.scalar(select(func.clock_timestamp()))
            candidates = db.scalars(select(Worker).where(Worker.last_heartbeat >= now - timedelta(seconds=worker_timeout))).all()
            if payload_target_worker_id:
                candidates = [w for w in candidates if w.id == payload_target_worker_id]
            matches = [m for w in candidates for m in (w.models or [{'model_id': w.model_id, 'model_revision': w.model_revision, 'supported_tasks': w.supported_tasks}])
                       if m['model_id'] == payload.model_id and payload.task_type in m['supported_tasks']]
            revisions = {m['model_revision'] for m in matches}
            if not revisions:
                raise HTTPException(409, 'No online worker supports this model and task')
            if len(revisions) > 1:
                raise HTTPException(409, 'Model revisions differ; select a specific worker')
            model_id, model_revision = payload.model_id, revisions.pop()
        if payload_target_worker_id is not None:
            worker = db.get(Worker, payload_target_worker_id)
            if worker is None:
                raise HTTPException(422, 'Selected worker does not exist')
            if owner_account_id is not None and worker.owner_account_id is None:
                raise HTTPException(409, 'Selected worker must be enrolled with a provider account')
            now = db.scalar(select(func.clock_timestamp()))
            if now - worker.last_heartbeat > timedelta(seconds=worker_timeout):
                raise HTTPException(409, 'Selected worker is offline; choose another worker')
            if not any((m['model_id'], m['model_revision']) == (model_id, model_revision) and payload.task_type in m['supported_tasks'] for m in (worker.models or [{'model_id': worker.model_id, 'model_revision': worker.model_revision, 'supported_tasks': worker.supported_tasks}])):
                raise HTTPException(422, 'Selected worker does not support this task and model revision')
            if request is not None and request.model_id is not None and request.model_id != model_id:
                raise HTTPException(409, 'Job model does not match the approved work request')
        job = Job(owner_account_id=owner_account_id, model_id=model_id, model_revision=model_revision, task_type=payload.task_type, optimization=payload.optimization,
                  target_worker_id=payload_target_worker_id,
                  total_inputs=len(payload.inputs), total_tasks=(len(payload.inputs) + chunk_size - 1) // chunk_size)
        db.add(job)
        db.flush()
        if owner_account_id is not None:
            from app.services.credits import reserve_job
            reserve_job(db, job, owner_account_id)
        for chunk in split_into_tasks(payload.inputs, chunk_size):
            if payload.instruction is not None:
                chunk['payload']['instruction'] = payload.instruction
            db.add(Task(job_id=job.id, **chunk))
        if request is not None:
            request.status = 'USED'
            request.job_id = job.id
            request.used_at = db.scalar(select(func.clock_timestamp()))
        db.flush()
    return job


def describe_job(job):
    fields = {name: getattr(job, name) for name in JobResponse.model_fields if name != 'progress_percentage'}
    return JobResponse(**fields, progress_percentage=round(100 * job.completed_tasks / job.total_tasks, 2))


def list_jobs(db, limit, offset):
    return [describe_job(job) for job in db.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset))]
