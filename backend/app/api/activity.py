"""Task ownership and execution metrics, scoped to the requesting account."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.security import require_account, owner_filter
from app.db.database import get_db
from app.models import Worker, Job, Task, TaskResult

router = APIRouter(tags=['activity'])


@router.get('/activity')
def activity(db: Session = Depends(get_db), request: Request = None):
    owner_id = owner_filter(require_account(request)) if request is not None else None
    job_scope = [] if owner_id is None else [Job.owner_account_id == owner_id]
    now = db.scalar(select(func.clock_timestamp()))
    task_query = select(Task, Job.task_type, Worker.name).join(Job, Job.id == Task.job_id)\
        .outerjoin(Worker, Worker.id == Task.assigned_worker_id).where(*job_scope)
    active = db.execute(task_query.where(Task.status.in_(['ASSIGNED', 'RUNNING']))
                        .order_by(Task.started_at).limit(100)).all()
    recent = db.execute(task_query.order_by(Task.created_at.desc(), Task.id).limit(30)).all()

    def describe(row):
        task, kind, name = row
        return dict(task_id=task.id, job_id=task.job_id, task_type=kind, status=task.status,
                    worker_id=task.assigned_worker_id, worker_name=name, attempt_count=task.attempt_count,
                    input_count=task.input_count, created_at=task.created_at, started_at=task.started_at,
                    completed_at=task.completed_at,
                    elapsed_seconds=round(max(0, ((task.completed_at or now) - task.started_at).total_seconds()), 1) if task.started_at else None,
                    queue_seconds=round(max(0, ((task.started_at or task.completed_at or now) - task.created_at).total_seconds()), 1),
                    error_code=(task.last_error or {}).get('code'))

    completed = db.execute(select(TaskResult.worker_id, func.count(),
        func.sum(func.jsonb_array_length(TaskResult.result)), func.avg(TaskResult.execution_time_ms))
        .join(Task, Task.id == TaskResult.task_id).join(Job, Job.id == Task.job_id)
        .where(*job_scope).group_by(TaskResult.worker_id)).all()
    counts = dict(db.execute(select(Task.status, func.count()).join(Job, Job.id == Task.job_id)
                            .where(*job_scope).group_by(Task.status)).all())
    retries = db.scalar(select(func.coalesce(func.sum(func.greatest(Task.attempt_count - 1, 0)), 0))
                        .select_from(Task).join(Job, Job.id == Task.job_id).where(*job_scope))
    return dict(as_of=now, active_tasks=[describe(r) for r in active], recent_tasks=[describe(r) for r in recent],
                task_counts=counts, retries=retries, worker_metrics=[dict(worker_id=w, completed_tasks=count,
                completed_inputs=inputs, average_execution_ms=round(float(avg), 1)) for w, count, inputs, avg in completed])
