from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.models import Account, ProviderPolicy, Task, Worker, WorkRequest
from app.schemas.work_request import WorkRequestCreate
from app.services.provider import admission_reasons, describe_policy


def _models(worker):
    return worker.models or [{'model_id': worker.model_id, 'model_revision': worker.model_revision,
                              'supported_tasks': worker.supported_tasks}]


def provider_directory(db, principal, settings):
    now = db.scalar(select(func.clock_timestamp()))
    workers = db.execute(select(Worker, Account).join(Account, Account.id == Worker.owner_account_id)
                         .where(Worker.owner_account_id.is_not(None), Worker.owner_account_id != principal.account_id,
                                Account.enabled.is_(True)).order_by(Account.name, Worker.name)).all()
    policies = {p.worker_id: p for p in db.scalars(select(ProviderPolicy))}
    counts = dict(db.execute(select(Task.assigned_worker_id, func.count()).where(
        Task.assigned_worker_id.is_not(None), Task.status.in_(['ASSIGNED', 'RUNNING']))
        .group_by(Task.assigned_worker_id)).all())
    result = []
    for worker, provider in workers:
        policy = policies.get(worker.id)
        active = counts.get(worker.id, 0)
        reasons = admission_reasons(worker, policy, now, active)
        if now - worker.last_heartbeat > timedelta(seconds=settings.worker_timeout_seconds):
            reasons.append('OFFLINE')
        inventory = [m for m in _models(worker) if m.get('model_id')]
        tasks = sorted({task for m in inventory for task in m.get('supported_tasks', [])})
        result.append(dict(provider_account_id=provider.id, provider_name=provider.name,
                           worker_id=worker.id, worker_name=worker.name,
                           accepting_new_tasks=not reasons, task_types=tasks, models=inventory,
                           active_tasks=active, max_concurrent_tasks=describe_policy(policy, worker)['max_concurrent_tasks'],
                           admission_reasons=reasons))
    return result


def create_request(db, principal, payload: WorkRequestCreate):
    if payload.provider_account_id == principal.account_id:
        raise HTTPException(422, 'Choose another account as the provider')
    with db.begin():
        provider = db.scalar(select(Account).where(Account.id == payload.provider_account_id, Account.enabled.is_(True)))
        if provider is None:
            raise HTTPException(404, 'Provider account not found')
        worker = db.scalar(select(Worker).where(Worker.id == payload.worker_id).with_for_update())
        if worker is None or worker.owner_account_id != provider.id:
            raise HTTPException(404, 'Provider worker not found')
        inventory = _models(worker)
        matches = [m for m in inventory if m.get('model_id') == payload.model_id and payload.task_type in m.get('supported_tasks', [])]
        if payload.model_id is None:
            matches = [m for m in inventory if payload.task_type in m.get('supported_tasks', [])]
        if not matches:
            raise HTTPException(409, 'That worker does not advertise the requested task and model')
        request = WorkRequest(requester_account_id=principal.account_id, provider_account_id=provider.id,
                              worker_id=worker.id, task_type=payload.task_type, model_id=payload.model_id)
        db.add(request)
        db.flush()
        return request


def list_requests(db, principal):
    # SQLAlchemy needs explicit aliases for the two account joins.
    requester = aliased(Account)
    provider = aliased(Account)
    query = select(WorkRequest, requester, provider, Worker).join(requester, requester.id == WorkRequest.requester_account_id).join(
        provider, provider.id == WorkRequest.provider_account_id).join(Worker, Worker.id == WorkRequest.worker_id)
    query = query.where(or_(WorkRequest.requester_account_id == principal.account_id,
                            WorkRequest.provider_account_id == principal.account_id)).order_by(WorkRequest.created_at.desc())
    return [dict(id=request.id, requester_account_id=request.requester_account_id,
                 requester_name=req.name, provider_account_id=request.provider_account_id,
                 provider_name=prov.name, worker_id=request.worker_id, worker_name=worker.name,
                 task_type=request.task_type, model_id=request.model_id, status=request.status,
                 job_id=request.job_id, created_at=request.created_at, decided_at=request.decided_at,
                 used_at=request.used_at) for request, req, prov, worker in db.execute(query).all()]


def decide_request(db, principal, request_id: UUID, status: str):
    with db.begin():
        request = db.scalar(select(WorkRequest).where(WorkRequest.id == request_id).with_for_update())
        if request is None:
            raise HTTPException(404, 'Work request not found')
        if request.provider_account_id != principal.account_id:
            raise HTTPException(404, 'Work request not found')
        if request.status != 'PENDING':
            raise HTTPException(409, f'Work request is already {request.status.lower()}')
        request.status = status
        request.decided_at = db.scalar(select(func.clock_timestamp()))
        return request
