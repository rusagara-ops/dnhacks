"""Scoped bearer authentication. Identity queries use their own short session.

Route services retain control of their transaction; an authorization SELECT must
not implicitly start a transaction in the session they are about to use.
"""
from dataclasses import dataclass
import hashlib
import secrets
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import inspect, select

from app.models.account import Account, Credential

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    account_id: UUID | None
    name: str
    role: str
    auth_mode: str
    credential_kind: str
    device_id: UUID | None = None


def new_token():
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def validate_database_auth_mode(engine, settings):
    """Never reopen account-owned data through the legacy shared demo identity."""
    if settings.auth_mode != 'demo':
        return
    # Inspect first so a pre-migration database keeps its existing not-ready
    # behavior. Honor SQLAlchemy's schema mapping used by isolated integration
    # databases; production uses the normal coordinator schema.
    schema = engine.get_execution_options().get('schema_translate_map', {}).get('coordinator', 'coordinator')
    with engine.connect() as connection:
        if not inspect(connection).has_table('accounts', schema=schema):
            return
        if connection.scalar(select(Account.id).limit(1)) is not None:
            raise RuntimeError('This database contains individual accounts. Use AUTH_MODE=controlled or a separate database for the shared demo.')


def _unauthorized():
    raise HTTPException(401, 'Invalid or revoked credential', headers={'WWW-Authenticate': 'Bearer'})


def auth_sessions(request):
    factory = request.app.state.sessions
    if factory is None:
        raise HTTPException(503, 'Database is not configured')
    return factory


def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    settings = request.app.state.settings
    token = credentials.credentials if credentials else ''
    expected = settings.api_token.get_secret_value() if settings.api_token else None
    if settings.auth_mode == 'demo':
        if expected and not secrets.compare_digest(token, expected):
            _unauthorized()
        principal = Principal(None, 'Demo operator', 'admin', 'demo', 'demo')
    elif not token:
        _unauthorized()
    elif expected and secrets.compare_digest(token, expected):
        principal = Principal(None, 'Setup administrator', 'admin', 'controlled', 'bootstrap')
    else:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with auth_sessions(request)() as db:
            row = db.execute(select(Credential, Account).join(Account, Account.id == Credential.account_id)
                .where(Credential.token_hash == token_hash, Credential.revoked_at.is_(None), Account.enabled.is_(True))).first()
            if row is None:
                _unauthorized()
            credential, account = row
            principal = Principal(account.id, account.name, account.role, 'controlled', credential.kind, credential.device_id)
    request.state.principal = principal
    return principal


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        _unauthorized()
    return principal


def require_account(request: Request) -> Principal:
    principal = get_principal(request)
    if principal.credential_kind not in ('account', 'demo'):
        raise HTTPException(403, 'An account credential is required')
    return principal


def require_admin(request: Request) -> Principal:
    principal = get_principal(request)
    if principal.role != 'admin' or principal.credential_kind == 'worker':
        raise HTTPException(403, 'An administrator account is required')
    return principal


def authorize_worker(request: Request, worker_id: UUID, allow_worker_credential=False) -> Principal:
    from app.models.worker import Worker
    principal = get_principal(request) if allow_worker_credential else require_account(request)
    if principal.auth_mode == 'demo':
        return principal
    if principal.credential_kind == 'bootstrap':
        raise HTTPException(403, 'Setup credentials cannot execute workloads')
    with auth_sessions(request)() as db:
        worker = db.get(Worker, worker_id)
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        if principal.credential_kind == 'worker':
            allowed = worker.owner_account_id == principal.account_id and worker.device_id == principal.device_id
        else:
            allowed = principal.role == 'admin' or worker.owner_account_id == principal.account_id
        if not allowed:
            raise HTTPException(403, 'This credential cannot manage that worker')
    return principal


def authorize_registration(request: Request, payload) -> Principal:
    principal = get_principal(request)
    if principal.auth_mode == 'demo':
        return principal
    if principal.credential_kind != 'worker':
        raise HTTPException(403, 'A worker installation credential is required')
    if payload.device_id != principal.device_id:
        raise HTTPException(403, 'Worker credential is bound to a different installation')
    if payload.previous_device_id not in (None, principal.device_id):
        raise HTTPException(403, 'Worker credentials cannot transfer another installation identity')
    return principal


def authorize_job(request: Request, job_id: UUID) -> Principal:
    from app.models.job import Job
    principal = require_account(request)
    if principal.auth_mode == 'demo':
        return principal
    with auth_sessions(request)() as db:
        job = db.get(Job, job_id)
        if job is None or (principal.role != 'admin' and job.owner_account_id != principal.account_id):
            # Do not disclose whether another member's job exists.
            raise HTTPException(404, 'Job not found')
    return principal


def owner_filter(principal):
    """None means the legacy/admin view; members receive only their own jobs."""
    return principal.account_id if principal.auth_mode == 'controlled' and principal.role != 'admin' else None
