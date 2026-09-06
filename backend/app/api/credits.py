from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, require_account, require_admin
from app.db.database import get_db
from app.schemas.credit import CreditBalanceResponse, CreditGrantRequest, CreditQuote
from app.schemas.job import JobCreateRequest
from app.services import credits

router = APIRouter(prefix='/credits', tags=['demo credits'])


@router.get('', response_model=CreditBalanceResponse)
def own_balance(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                principal: Principal = Depends(require_account), db: Session = Depends(get_db)):
    if principal.account_id is None:
        raise HTTPException(409, 'Sign in with an individual controlled-mode account to use demo credits')
    with db.begin():
        return credits.balance(db, principal.account_id, limit, offset)


@router.post('/quote', response_model=CreditQuote)
def quote_job(payload: JobCreateRequest, principal: Principal = Depends(require_account)):
    return credits.quote(payload)


@router.post('/grants', response_model=CreditBalanceResponse)
def grant(payload: CreditGrantRequest, principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if principal.auth_mode != 'controlled':
        raise HTTPException(409, 'Enable AUTH_MODE=controlled to grant credits to individual accounts')
    with db.begin():
        credits.grant_credits(db, payload.account_id, payload.amount, payload.request_id)
        return credits.balance(db, payload.account_id)
