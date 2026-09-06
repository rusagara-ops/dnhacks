import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models import Worker
from app.schemas.worker import HeartbeatRequest, HeartbeatResponse, WorkerRegisterRequest, WorkerRegisterResponse, WorkerResponse
from app.services.task_service import renew_heartbeat
from app.services import worker_service
from app.schemas.task import NextTaskResponse
from app.services.scheduler import get_next_task

router = APIRouter(prefix='/workers', tags=['workers'])
logger = logging.getLogger(__name__)


@router.post('/register', status_code=201, response_model=WorkerRegisterResponse)
def register(payload: WorkerRegisterRequest, request: Request, db: Session = Depends(get_db)):
    worker = worker_service.register_worker(db, payload)
    logger.info('Worker registered: %s', worker.id)
    return WorkerRegisterResponse(worker_id=worker.id, heartbeat_interval_seconds=request.app.state.settings.heartbeat_interval_seconds)


@router.get('', response_model=list[WorkerResponse])
def workers(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), include_history: bool = False, db: Session = Depends(get_db)):
    return worker_service.list_workers(db, request.app.state.settings.worker_timeout_seconds, limit, offset, include_history)


@router.post('/{worker_id}/heartbeat', response_model=HeartbeatResponse)
def heartbeat(worker_id: UUID, payload: HeartbeatRequest, request: Request, db: Session = Depends(get_db)):
    expiry = renew_heartbeat(db, worker_id, payload, request.app.state.settings)
    return HeartbeatResponse(lease_expires_at=expiry)


@router.post('/{worker_id}/next-task', response_model=NextTaskResponse)
def next_task(worker_id: UUID, request: Request, db: Session = Depends(get_db)):
    return get_next_task(db, worker_id, request.app.state.settings)
