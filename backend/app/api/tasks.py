from uuid import UUID
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.security import authorize_worker
from app.schemas.task import TaskCompleteRequest, TaskFailRequest, TaskMutationResponse
from app.services.task_service import complete_task, fail_task

router = APIRouter(prefix='/tasks', tags=['tasks'])


@router.post('/{task_id}/complete', response_model=TaskMutationResponse)
def complete(task_id: UUID, payload: TaskCompleteRequest, request: Request, db: Session = Depends(get_db)):
    authorize_worker(request, payload.worker_id, allow_worker_credential=True)
    return complete_task(db, task_id, payload)


@router.post('/{task_id}/fail', response_model=TaskMutationResponse)
def fail(task_id: UUID, payload: TaskFailRequest, request: Request, db: Session = Depends(get_db)):
    authorize_worker(request, payload.worker_id, allow_worker_credential=True)
    return fail_task(db, task_id, payload)
