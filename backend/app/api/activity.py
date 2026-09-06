"""Authenticated task ownership and execution metrics for the demo dashboard."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models import Worker, Job, Task, TaskResult

router=APIRouter(tags=['activity'])

@router.get('/activity')
def activity(db: Session=Depends(get_db)):
    now=db.scalar(select(func.clock_timestamp()))
    active=db.execute(select(Task,Job.task_type,Worker.name).join(Job,Job.id==Task.job_id)
        .outerjoin(Worker,Worker.id==Task.assigned_worker_id)
        .where(Task.status.in_(['ASSIGNED','RUNNING'])).order_by(Task.started_at).limit(100)).all()
    recent=db.execute(select(Task,Job.task_type,Worker.name).join(Job,Job.id==Task.job_id)
        .outerjoin(Worker,Worker.id==Task.assigned_worker_id)
        .order_by(Task.created_at.desc(),Task.id).limit(30)).all()
    def describe(row):
        task,kind,name=row
        return dict(task_id=task.id,job_id=task.job_id,task_type=kind,status=task.status,
                    worker_id=task.assigned_worker_id,worker_name=name,attempt_count=task.attempt_count,
                    input_count=task.input_count,created_at=task.created_at,started_at=task.started_at,
                    completed_at=task.completed_at,
                    elapsed_seconds=round(max(0,((task.completed_at or now)-task.started_at).total_seconds()),1) if task.started_at else None,
                    queue_seconds=round(max(0,((task.started_at or task.completed_at or now)-task.created_at).total_seconds()),1),
                    error_code=(task.last_error or {}).get('code'))
    completed=db.execute(select(TaskResult.worker_id,func.count(),
        func.sum(func.jsonb_array_length(TaskResult.result)),func.avg(TaskResult.execution_time_ms))
        .group_by(TaskResult.worker_id)).all()
    counts=dict(db.execute(select(Task.status,func.count()).group_by(Task.status)).all())
    retries=db.scalar(select(func.coalesce(func.sum(func.greatest(Task.attempt_count-1,0)),0)))
    return dict(as_of=now,active_tasks=[describe(r) for r in active],recent_tasks=[describe(r) for r in recent],
                task_counts=counts,retries=retries,worker_metrics=[dict(worker_id=w,completed_tasks=count,
                completed_inputs=inputs,average_execution_ms=round(float(avg),1)) for w,count,inputs,avg in completed])
