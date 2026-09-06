from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import Job, Task, Worker
from app.schemas.job import JobResponse

CHUNK_SIZE = 25


def split_into_tasks(inputs, chunk_size=CHUNK_SIZE):
    for start in range(0, len(inputs), chunk_size):
        chunk = inputs[start:start + chunk_size]
        yield {'start_index': start, 'input_count': len(chunk), 'payload': {
            'inputs': [{'index': start + offset, 'text': value} for offset, value in enumerate(chunk)]
        }}


def create_job(db, payload, model_id=None, model_revision=None, worker_timeout=15):
    chunk_size = CHUNK_SIZE if payload.task_type == 'sentiment-classification' else 1
    # The job and every chunk must become visible together, or not at all.
    with db.begin():
        if payload.target_worker_id is not None:
            worker = db.get(Worker, payload.target_worker_id)
            if worker is None:
                raise HTTPException(422, 'Selected worker does not exist')
            now = db.scalar(select(func.clock_timestamp()))
            if now - worker.last_heartbeat > timedelta(seconds=worker_timeout):
                raise HTTPException(409, 'Selected worker is offline; choose another worker')
            if (worker.model_id, worker.model_revision) != (model_id, model_revision) or payload.task_type not in worker.supported_tasks:
                raise HTTPException(422, 'Selected worker does not support this task and model revision')
        job = Job(model_id=model_id, model_revision=model_revision, task_type=payload.task_type, optimization=payload.optimization,
                  target_worker_id=payload.target_worker_id,
                  total_inputs=len(payload.inputs), total_tasks=(len(payload.inputs) + chunk_size - 1) // chunk_size)
        db.add(job)
        db.flush()
        for chunk in split_into_tasks(payload.inputs, chunk_size):
            if payload.instruction is not None:
                chunk['payload']['instruction'] = payload.instruction
            db.add(Task(job_id=job.id, **chunk))
        db.flush()
    return job


def describe_job(job):
    fields = {name: getattr(job, name) for name in JobResponse.model_fields if name != 'progress_percentage'}
    return JobResponse(**fields, progress_percentage=round(100 * job.completed_tasks / job.total_tasks, 2))


def list_jobs(db, limit, offset):
    return [describe_job(job) for job in db.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset))]
