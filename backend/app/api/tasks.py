from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.task import TaskCompleteRequest, TaskFailRequest, TaskMutationResponse
from app.services.task_service import complete_task, fail_task

router = APIRouter(prefix='/tasks', tags=['tasks'])


@router.post('/{task_id}/complete', response_model=TaskMutationResponse)
def complete(task_id: UUID, payload: TaskCompleteRequest, db: Session = Depends(get_db)):
    return complete_task(db, task_id, payload)


@router.post('/{task_id}/fail', response_model=TaskMutationResponse)
def fail(task_id: UUID, payload: TaskFailRequest, db: Session = Depends(get_db)):
    return fail_task(db, task_id, payload)
