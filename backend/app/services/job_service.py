from sqlalchemy import select
from app.models import Job, Task
from app.schemas.job import JobResponse

CHUNK_SIZE = 25


def split_into_tasks(inputs):
    for start in range(0, len(inputs), CHUNK_SIZE):
        chunk = inputs[start:start + CHUNK_SIZE]
        yield {'start_index': start, 'input_count': len(chunk), 'payload': {
            'inputs': [{'index': start + offset, 'text': value} for offset, value in enumerate(chunk)]
        }}


def create_job(db, payload):
    # The job and every chunk must become visible together, or not at all.
    with db.begin():
        job = Job(task_type=payload.task_type, optimization=payload.optimization,
                  total_inputs=len(payload.inputs), total_tasks=(len(payload.inputs) + CHUNK_SIZE - 1) // CHUNK_SIZE)
        db.add(job)
        db.flush()
        db.add_all(Task(job_id=job.id, **chunk) for chunk in split_into_tasks(payload.inputs))
        db.flush()
    return job


def describe_job(job):
    fields = {name: getattr(job, name) for name in JobResponse.model_fields if name != 'progress_percentage'}
    return JobResponse(**fields, progress_percentage=round(100 * job.completed_tasks / job.total_tasks, 2))


def list_jobs(db, limit, offset):
    return [describe_job(job) for job in db.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset))]
