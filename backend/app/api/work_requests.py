from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.security import require_account
from app.db.database import get_db
from app.schemas.work_request import ProviderDirectoryItem, WorkRequestCreate, WorkRequestResponse
from app.services.work_requests import create_request, decide_request, list_requests, provider_directory

router = APIRouter(prefix='/work-requests', tags=['work-requests'])


@router.get('/providers', response_model=list[ProviderDirectoryItem])
def providers(request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    return provider_directory(db, principal, request.app.state.settings)


@router.get('', response_model=list[WorkRequestResponse])
def requests(request: Request, db: Session = Depends(get_db)):
    require_account(request)
    return list_requests(db, request.state.principal)


@router.post('', status_code=201, response_model=WorkRequestResponse)
def create(payload: WorkRequestCreate, request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    created = create_request(db, principal, payload)
    # Return through the same projection used by the list endpoint.
    return next(item for item in list_requests(db, principal) if item['id'] == created.id)


@router.post('/{request_id}/approve', response_model=WorkRequestResponse)
def approve(request_id: UUID, request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    decide_request(db, principal, request_id, 'APPROVED')
    return next(item for item in list_requests(db, principal) if item['id'] == request_id)


@router.post('/{request_id}/decline', response_model=WorkRequestResponse)
def decline(request_id: UUID, request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    decide_request(db, principal, request_id, 'DECLINED')
    return next(item for item in list_requests(db, principal) if item['id'] == request_id)
