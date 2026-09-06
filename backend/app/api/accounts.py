from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import get_principal, new_token, require_account, require_admin
from app.db.database import get_db
from app.models.account import Account, Credential
from app.models.worker import Worker
from app.schemas.account import AccountCreate, AccountCreated, AccountResponse, AccountCredentialCreate, CredentialCreated, CredentialResponse, WorkerCredentialCreate

router = APIRouter(tags=['accounts'])


def _controlled(request):
    if request.app.state.settings.auth_mode != 'controlled':
        raise HTTPException(409, 'Enable AUTH_MODE=controlled to manage individual accounts')


@router.get('/me')
def me(request: Request):
    return asdict(get_principal(request))


@router.get('/accounts', response_model=list[AccountResponse])
def accounts(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    _controlled(request)
    return db.scalars(select(Account).order_by(Account.created_at, Account.id)).all()


@router.post('/accounts', status_code=201, response_model=AccountCreated)
def create_account(payload: AccountCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    require_admin(request)
    _controlled(request)
    token, token_hash = new_token()
    with db.begin():
        account = Account(name=payload.name, role=payload.role)
        db.add(account)
        db.flush()
        db.add(Credential(account_id=account.id, token_hash=token_hash, kind='account', label='Initial account credential'))
    response.headers['Cache-Control'] = 'no-store'
    return AccountCreated(account=AccountResponse.model_validate(account), token=token)


@router.get('/accounts/{account_id}/credentials', response_model=list[CredentialResponse])
def account_credentials(account_id: UUID, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    _controlled(request)
    if db.get(Account, account_id) is None:
        raise HTTPException(404, 'Account not found')
    return db.scalars(select(Credential).where(Credential.account_id == account_id)
        .order_by(Credential.created_at.desc(), Credential.id)).all()


@router.post('/accounts/{account_id}/credentials', status_code=201, response_model=CredentialCreated)
def recover_account_credential(account_id: UUID, payload: AccountCredentialCreate, request: Request,
                               response: Response, db: Session = Depends(get_db)):
    require_admin(request)
    _controlled(request)
    token, token_hash = new_token()
    with db.begin():
        account = db.scalar(select(Account).where(Account.id == account_id).with_for_update())
        if account is None:
            raise HTTPException(404, 'Account not found')
        if not account.enabled:
            raise HTTPException(409, 'A disabled account cannot receive a replacement credential')
        credential = Credential(account_id=account.id, token_hash=token_hash, kind='account', label=payload.label)
        db.add(credential)
        db.flush()
    # Recovery adds a credential; revocation is a separate explicit operation so
    # the administrator can hand over the replacement before retiring the old one.
    response.headers['Cache-Control'] = 'no-store'
    return CredentialCreated(credential=CredentialResponse.model_validate(credential), token=token)


@router.get('/credentials', response_model=list[CredentialResponse])
def credentials(request: Request, db: Session = Depends(get_db)):
    principal = require_account(request)
    _controlled(request)
    return db.scalars(select(Credential).where(Credential.account_id == principal.account_id)
        .order_by(Credential.created_at.desc(), Credential.id)).all()


@router.post('/credentials', status_code=201, response_model=CredentialCreated)
def issue_worker_credential(payload: WorkerCredentialCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    principal = require_account(request)
    _controlled(request)
    token, token_hash = new_token()
    with db.begin():
        # Serialize with enrollment/registration of this installation. A token may
        # be minted before the worker first connects, but never for another owner.
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(payload.device_id)))))
        existing = db.scalar(select(Worker).where(Worker.device_id == payload.device_id).with_for_update())
        if existing is not None and existing.owner_account_id != principal.account_id:
            raise HTTPException(403, 'Enroll this installation under your account before issuing its credential')
        credential = Credential(account_id=principal.account_id, token_hash=token_hash, kind='worker',
                                device_id=payload.device_id, label=payload.label)
        db.add(credential)
        db.flush()
    response.headers['Cache-Control'] = 'no-store'
    return CredentialCreated(credential=CredentialResponse.model_validate(credential), token=token)


@router.post('/credentials/{credential_id}/revoke', response_model=CredentialResponse)
def revoke(credential_id: UUID, request: Request, db: Session = Depends(get_db)):
    principal = get_principal(request)
    if principal.credential_kind == 'bootstrap':
        require_admin(request)
    else:
        require_account(request)
    _controlled(request)
    with db.begin():
        credential = db.scalar(select(Credential).where(Credential.id == credential_id).with_for_update())
        if credential is None or (principal.role != 'admin' and credential.account_id != principal.account_id):
            raise HTTPException(404, 'Credential not found')
        if credential.revoked_at is None:
            credential.revoked_at = db.scalar(select(func.clock_timestamp()))
    return credential


@router.post('/accounts/{account_id}/workers/{worker_id}/enroll')
def enroll_existing_worker(account_id: UUID, worker_id: UUID, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    _controlled(request)
    with db.begin():
        account = db.get(Account, account_id)
        if account is None or not account.enabled:
            raise HTTPException(404, 'Enabled account not found')
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        if worker.owner_account_id not in (None, account_id):
            raise HTTPException(409, 'An owned installation cannot be transferred through enrollment')
        if worker.active_tasks:
            raise HTTPException(409, 'Drain active assignments before enrolling this worker')
        if worker.device_id is None:
            raise HTTPException(409, 'Restart this worker with a persistent installation ID before enrollment')
        worker.owner_account_id = account_id
    return {'worker_id': worker.id, 'owner_account_id': account_id, 'device_id': worker.device_id}
