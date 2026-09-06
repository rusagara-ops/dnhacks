from uuid import UUID
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.core.security import require_account, authorize_worker
from app.db.database import get_db
from app.schemas.provider import ProviderPolicyUpdate
from app.services.provider import provider_workers, set_policy

router = APIRouter(prefix='/provider', tags=['provider'])


@router.get('/workers')
def workers(request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    return provider_workers(db, principal, request.app.state.settings)


@router.post('/workers/{worker_id}/policy')
def policy(worker_id: UUID, payload: ProviderPolicyUpdate, request: Request, db: Session = Depends(get_db)):
    authorize_worker(request, worker_id)
    return set_policy(db, worker_id, payload)
