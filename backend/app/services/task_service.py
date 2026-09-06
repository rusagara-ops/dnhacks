from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import Worker, Task, Job, TaskResult
from app.schemas.task import TaskMutationResponse, JobResultResponse, FailedTask, GeneratedText, Prediction, TaskDetail, ExtractionResult

ACTIVE = ['ASSIGNED', 'RUNNING']


def locked_assignment(db, task_id, worker_id):
    # Global write lock order: worker -> task -> job.
    worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
    if worker is None:
        raise HTTPException(404, 'Worker not found')
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(404, 'Task not found')
    return worker, task


def validate_assignment(task, worker_id, assignment_id, now):
    if task.assigned_worker_id != worker_id or task.assignment_id != assignment_id:
        raise HTTPException(409, 'Assignment is no longer current')
    if task.status not in ACTIVE or task.lease_expires_at is None or task.lease_expires_at <= now:
        raise HTTPException(409, 'Assignment is not active or has expired')


def finalize_job(job, now):
    if job.completed_tasks + job.failed_tasks == job.total_tasks:
        job.status = 'FAILED' if job.failed_tasks else 'COMPLETED'
        job.completed_at = now


def complete_task(db, task_id, payload):
    with db.begin():
        worker, task = locked_assignment(db, task_id, payload.worker_id)
        if task.status == 'COMPLETED' and task.assigned_worker_id == worker.id and task.assignment_id == payload.assignment_id:
            return TaskMutationResponse(status='already_completed')
        now = db.scalar(select(func.clock_timestamp()))
        validate_assignment(task, worker.id, payload.assignment_id, now)
        expected = {item['index'] for item in task.payload['inputs']}
        received = [item.index for item in payload.results]
        if len(received) != len(expected) or set(received) != expected:
            raise HTTPException(422, 'Return exactly one prediction for every assigned input index')
        job = db.scalar(select(Job).where(Job.id == task.job_id).with_for_update())
        expected_type = {'sentiment-classification': Prediction, 'information-extraction': ExtractionResult}.get(job.task_type, GeneratedText)
        if any(not isinstance(item, expected_type) for item in payload.results):
            raise HTTPException(422, 'Result format does not match the job task type')
        db.add(TaskResult(task_id=task.id, worker_id=worker.id,
                          inference_metrics=payload.inference_metrics.model_dump() if payload.inference_metrics else None,
                          result=[p.model_dump() for p in payload.results], execution_time_ms=payload.execution_time_ms))
        task.status = 'COMPLETED'
        task.completed_at = now
        worker.active_tasks = max(0, worker.active_tasks - 1)
        job.completed_tasks += 1
        finalize_job(job, now)
    return TaskMutationResponse(status='completed')


def release_task(db, worker, task, now, code, message):
    job = db.scalar(select(Job).where(Job.id == task.job_id).with_for_update())
    task.last_error = {'code': code, 'message': message,
                       'assignment_id': str(task.assignment_id), 'worker_id': str(worker.id)}
    task.assigned_worker_id = None
    task.assignment_id = None
    task.lease_expires_at = None
    worker.active_tasks = max(0, worker.active_tasks - 1)
    if task.attempt_count >= 3:
        task.status = 'FAILED'
        task.completed_at = now
        job.failed_tasks += 1
        finalize_job(job, now)
        return 'failed'
    task.status = 'QUEUED'
    task.started_at = None
    task.completed_at = None
    return 'requeued'


def fail_task(db, task_id, payload):
    with db.begin():
        worker, task = locked_assignment(db, task_id, payload.worker_id)
        previous = task.last_error or {}
        if previous.get('assignment_id') == str(payload.assignment_id) and previous.get('worker_id') == str(worker.id):
            return TaskMutationResponse(status='already_failed')
        now = db.scalar(select(func.clock_timestamp()))
        validate_assignment(task, worker.id, payload.assignment_id, now)
        status = release_task(db, worker, task, now, payload.error.code, payload.error.message)
    return TaskMutationResponse(status=status)


def renew_heartbeat(db, worker_id, payload, settings):
    with db.begin():
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        now = db.scalar(select(func.clock_timestamp()))
        expiry = None
        if payload.task_id:
            task = db.scalar(select(Task).where(Task.id == payload.task_id).with_for_update())
            if task is None:
                raise HTTPException(404, 'Task not found')
            validate_assignment(task, worker.id, payload.assignment_id, now)
            deadline = task.started_at + timedelta(seconds=settings.task_max_runtime_seconds)
            if now >= deadline:
                raise HTTPException(409, 'Maximum assignment runtime exceeded')
            expiry = min(now + timedelta(seconds=settings.task_lease_seconds), deadline)
            task.lease_expires_at = expiry
            task.status = 'RUNNING'
        if payload.ram_available_gb is not None and payload.ram_available_gb > worker.ram_gb:
            raise HTTPException(422, 'Available RAM exceeds total RAM')
        if worker.gpu_memory_kind == 'unified' and payload.gpu_available_gb is not None:
            raise HTTPException(422, 'Unified memory has no separate available GPU memory pool')
        if payload.gpu_available_gb is not None and worker.gpu_memory_gb is not None and payload.gpu_available_gb > worker.gpu_memory_gb:
            raise HTTPException(422, 'Available GPU memory exceeds total GPU memory')
        worker.ram_available_gb = payload.ram_available_gb
        worker.gpu_available_gb = payload.gpu_available_gb
        worker.gpu_model_memory_gb = payload.gpu_model_memory_gb
        worker.cpu_utilization = payload.cpu_utilization
        worker.memory_utilization = payload.memory_utilization
        if worker.models:
            db.flush()
            worker.active_tasks = db.scalar(select(func.count()).select_from(Task).where(
                Task.assigned_worker_id == worker.id, Task.status.in_(ACTIVE)))
        else:
            worker.active_tasks = payload.active_tasks
        worker.last_heartbeat = now
    return expiry


def job_results(db, job_id):
    with db.begin():
        # A shared job lock keeps counters/results consistent with concurrent completion.
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update(read=True))
        if job is None:
            raise HTTPException(404, 'Job not found')
        rows = db.execute(select(Task, TaskResult).outerjoin(TaskResult, TaskResult.task_id == Task.id)
                          .where(Task.job_id == job.id).order_by(Task.start_index)).all()
        worker_ids = {t.assigned_worker_id for t, r in rows if t.assigned_worker_id}
        names = dict(db.execute(select(Worker.id, Worker.name).where(Worker.id.in_(worker_ids))).all())
        details = [TaskDetail(task_id=t.id, input_start_index=t.start_index, input_count=t.input_count,
                              status=t.status, worker_id=t.assigned_worker_id,
                              worker_name=names.get(t.assigned_worker_id), attempt_count=t.attempt_count,
                              inference_metrics=r.inference_metrics if r else None,
                              execution_time_ms=r.execution_time_ms if r else None) for t, r in rows]
        predictions = [p for task, result in rows if result for p in result.result]
        failures = [FailedTask(task_id=t.id, input_start_index=t.start_index, input_count=t.input_count,
                               error_code=(t.last_error or {}).get('code', 'RETRY_LIMIT_EXCEEDED'))
                    for t, result in rows if t.status == 'FAILED']
        return JobResultResponse(job_id=job.id, status=job.status, is_final=job.status in ['COMPLETED','FAILED'],
                                 total_inputs=job.total_inputs, completed_inputs=len(predictions),
                                 failed_inputs=sum(t.input_count for t in failures),
                                 results=sorted(predictions, key=lambda p:p['index']), failed_tasks=failures, tasks=details)
