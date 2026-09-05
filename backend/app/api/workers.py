import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models import Worker
from app.schemas.worker import HeartbeatRequest, HeartbeatResponse, WorkerRegisterRequest, WorkerRegisterResponse, WorkerResponse
from app.services import worker_service

router = APIRouter(prefix='/workers', tags=['workers'])
logger = logging.getLogger(__name__)


@router.post('/register', status_code=201, response_model=WorkerRegisterResponse)
def register(payload: WorkerRegisterRequest, request: Request, db: Session = Depends(get_db)):
    worker = worker_service.register_worker(db, payload)
    logger.info('Worker registered: %s', worker.id)
    return WorkerRegisterResponse(worker_id=worker.id, heartbeat_interval_seconds=request.app.state.settings.heartbeat_interval_seconds)


@router.get('', response_model=list[WorkerResponse])
def workers(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return worker_service.list_workers(db, request.app.state.settings.worker_timeout_seconds, limit, offset)


@router.post('/{worker_id}/heartbeat', response_model=HeartbeatResponse)
def heartbeat(worker_id: UUID, payload: HeartbeatRequest, db: Session = Depends(get_db)):
    worker = db.get(Worker, worker_id, with_for_update=True)
    if worker is None:
        raise HTTPException(404, 'Worker not found')
    for key, value in payload.model_dump().items():
        setattr(worker, key, value)
    worker.last_heartbeat = func.clock_timestamp()
    db.commit()
    return HeartbeatResponse()
