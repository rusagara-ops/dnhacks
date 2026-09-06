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
    active=db.execute(select(Task,Job.task_type,Job.model_id,Job.model_revision,Worker.name,
                             TaskResult.execution_time_ms,TaskResult.inference_metrics)
        .join(Job,Job.id==Task.job_id)
        .outerjoin(Worker,Worker.id==Task.assigned_worker_id)
        .outerjoin(TaskResult,TaskResult.task_id==Task.id)
        .where(Task.status.in_(['ASSIGNED','RUNNING'])).order_by(Task.started_at).limit(100)).all()
    recent=db.execute(select(Task,Job.task_type,Job.model_id,Job.model_revision,Worker.name,
                             TaskResult.execution_time_ms,TaskResult.inference_metrics)
        .join(Job,Job.id==Task.job_id)
        .outerjoin(Worker,Worker.id==Task.assigned_worker_id)
        .outerjoin(TaskResult,TaskResult.task_id==Task.id)
        .order_by(Task.created_at.desc(),Task.id).limit(30)).all()
    def describe(row):
        task,kind,model_id,model_revision,name,execution_time_ms,inference_metrics=row
        return dict(task_id=task.id,job_id=task.job_id,task_type=kind,status=task.status,
                    model_id=model_id,model_revision=model_revision,
                    worker_id=task.assigned_worker_id,worker_name=name,attempt_count=task.attempt_count,
                    start_index=task.start_index,input_count=task.input_count,created_at=task.created_at,started_at=task.started_at,
                    completed_at=task.completed_at,
                    elapsed_seconds=round(max(0,((task.completed_at or now)-task.started_at).total_seconds()),1) if task.started_at else None,
                    queue_seconds=round(max(0,((task.started_at or task.completed_at or now)-task.created_at).total_seconds()),1),
                    execution_time_ms=execution_time_ms,inference_metrics=inference_metrics,
                    error_code=(task.last_error or {}).get('code'))
    completed=db.execute(select(TaskResult.worker_id,func.count(),
        func.sum(func.jsonb_array_length(TaskResult.result)),func.avg(TaskResult.execution_time_ms))
        .group_by(TaskResult.worker_id)).all()
    # Count accepted results by worker and type. The dashboard resolves identity
    # through worker history without merging unrelated devices by display name.
    by_type=db.execute(select(TaskResult.worker_id,Job.task_type,func.count())
        .join(Task,Task.id==TaskResult.task_id)
        .join(Job,Job.id==Task.job_id)
        .group_by(TaskResult.worker_id,Job.task_type)).all()
    counts=dict(db.execute(select(Task.status,func.count()).group_by(Task.status)).all())
    retries=db.scalar(select(func.coalesce(func.sum(func.greatest(Task.attempt_count-1,0)),0)))
    return dict(as_of=now,active_tasks=[describe(r) for r in active],recent_tasks=[describe(r) for r in recent],
                task_counts=counts,retries=retries,worker_metrics=[dict(worker_id=w,completed_tasks=count,
                completed_inputs=inputs,average_execution_ms=round(float(avg),1)) for w,count,inputs,avg in completed],
                worker_task_types=[dict(worker_id=w,task_type=kind,completed_tasks=count) for w,kind,count in by_type])
