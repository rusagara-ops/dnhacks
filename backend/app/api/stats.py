from datetime import timedelta
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models import Worker, Job, Task, TaskResult

router = APIRouter(tags=['stats'])


class StatsResponse(BaseModel):
    workers_online: int
    workers_available: int
    workers_busy: int
    jobs_queued: int
    jobs_running: int
    jobs_completed: int
    jobs_failed: int
    tasks_completed: int
    total_inferences: int


def get_stats(db, timeout):
    online = Worker.last_heartbeat >= func.statement_timestamp() - timedelta(seconds=timeout)
    def count(model, *conditions):
        return select(func.count()).select_from(model).where(*conditions).scalar_subquery()
    # One SQL statement provides a consistent snapshot of all dashboard counters.
    query = select(
        count(Worker, online).label('workers_online'),
        count(Worker, online, Worker.active_tasks == 0).label('workers_available'),
        count(Worker, online, Worker.active_tasks > 0).label('workers_busy'),
        *[count(Job, Job.status == status).label('jobs_' + status.lower())
          for status in ['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED']],
        count(Task, Task.status == 'COMPLETED').label('tasks_completed'),
        select(func.coalesce(func.sum(func.jsonb_array_length(TaskResult.result)), 0)).scalar_subquery().label('total_inferences'),
    )
    return StatsResponse(**db.execute(query).mappings().one())


@router.get('/stats', response_model=StatsResponse)
def stats(request: Request, db: Session = Depends(get_db)):
    return get_stats(db, request.app.state.settings.worker_timeout_seconds)
