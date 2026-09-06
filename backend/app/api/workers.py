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
from app.schemas.worker import WorkerLocationsResponse, WorkerLocationUpdate, WorkerDiscoveryRequest
from app.services.locations import list_locations

router = APIRouter(prefix='/workers', tags=['workers'])
logger = logging.getLogger(__name__)


@router.get('/locations', response_model=WorkerLocationsResponse)
def locations(request: Request,
              latitude: float | None = Query(None, ge=-90, le=90, allow_inf_nan=False),
              longitude: float | None = Query(None, ge=-180, le=180, allow_inf_nan=False),
              task_type: str | None = Query(None, min_length=1, max_length=100),
              gpu_only: bool = False, online_only: bool = False,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db)):
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, 'Provide both latitude and longitude')
    return list_locations(db, request.app.state.settings, latitude, longitude, task_type,
                          gpu_only, online_only, limit, offset)


@router.post('/register', status_code=201, response_model=WorkerRegisterResponse)
def register(payload: WorkerRegisterRequest, request: Request, db: Session = Depends(get_db)):
    worker = worker_service.register_worker(db, payload)
    logger.info('Worker registered: %s', worker.id)
    return WorkerRegisterResponse(worker_id=worker.id, heartbeat_interval_seconds=request.app.state.settings.heartbeat_interval_seconds)


@router.post('/locations/search', response_model=WorkerLocationsResponse)
def nearby_workers(payload: WorkerDiscoveryRequest, request: Request, db: Session = Depends(get_db)):
    # Visitor coordinates go in the body, not URL/access-log query strings.
    return list_locations(db, request.app.state.settings, **payload.model_dump())


@router.get('', response_model=list[WorkerResponse])
def workers(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), include_history: bool = False, db: Session = Depends(get_db)):
    return worker_service.list_workers(db, request.app.state.settings.worker_timeout_seconds, limit, offset, include_history)


@router.post('/{worker_id}/heartbeat', response_model=HeartbeatResponse)
def heartbeat(worker_id: UUID, payload: HeartbeatRequest, request: Request, db: Session = Depends(get_db)):
    expiry = renew_heartbeat(db, worker_id, payload, request.app.state.settings)
    return HeartbeatResponse(lease_expires_at=expiry)


@router.post('/{worker_id}/location', response_model=WorkerResponse)
def set_location(worker_id: UUID, payload: WorkerLocationUpdate, request: Request, db: Session = Depends(get_db)):
    return worker_service.update_location(db, worker_id, payload.location, request.app.state.settings.worker_timeout_seconds)


@router.post('/{worker_id}/next-task', response_model=NextTaskResponse)
def next_task(worker_id: UUID, request: Request, db: Session = Depends(get_db)):
    return get_next_task(db, worker_id, request.app.state.settings)
