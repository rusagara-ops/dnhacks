from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.model_registry import MODEL_REGISTRY
from app.db.database import get_db
from app.core.security import require_account, authorize_job
from app.models import Job, Worker, Task
from app.services.eligibility import eligibility_reasons
from app.models.provider import ProviderPolicy
from app.services.provider import admission_reasons

router = APIRouter(tags=['inference awareness'])


@router.get('/models')
def models(request: Request):
    require_account(request)
    settings = request.app.state.settings
    from datetime import timedelta
    inventory = []
    if request.app.state.sessions is not None:
        with request.app.state.sessions() as db:
            now = db.scalar(select(func.clock_timestamp()))
            workers = db.scalars(select(Worker).where(
                Worker.last_heartbeat >= now - timedelta(seconds=settings.worker_timeout_seconds)))
            inventory = [m for w in workers for m in (w.models or [
                {'model_id': w.model_id, 'model_revision': w.model_revision}])]
    result = []
    for key, spec in MODEL_REGISTRY.items():
        revisions = {m['model_revision'] for m in inventory if m['model_id'] == key and m['model_revision']}
        is_default = key == settings.inference_model_id and bool(settings.inference_model_revision)
        revision = next(iter(revisions)) if len(revisions) == 1 else settings.inference_model_revision if is_default and not revisions else None
        result.append(dict(**spec.describe(), configured=is_default or bool(revisions), model_revision=revision))
    return result


@router.get('/jobs/{job_id}/eligibility')
def job_eligibility(job_id: UUID, request: Request, limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    authorize_job(request, job_id)
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    now = db.scalar(select(func.clock_timestamp()))
    workers = db.scalars(select(Worker).order_by(Worker.created_at.desc(), Worker.id).limit(limit).offset(offset))
    rows = []
    for worker in workers:
        active_slots = list(db.scalars(select(Task.model_slot).where(
            Task.assigned_worker_id == worker.id, Task.status.in_(['ASSIGNED', 'RUNNING']))))
        reasons = eligibility_reasons(worker, job.model_id, job.model_revision, job.task_type,
                                      now, request.app.state.settings.worker_timeout_seconds,
                                      active_model_ids=set(active_slots))
        reasons.extend(admission_reasons(worker, db.get(ProviderPolicy, worker.id), now,
                                         len(active_slots), job.task_type))
        if job.owner_account_id is not None and worker.owner_account_id is None:
            reasons.append('PROVIDER_NOT_ENROLLED')
        if job.target_worker_id is not None and job.target_worker_id != worker.id:
            reasons.append('DIFFERENT_TARGET_WORKER')
        rows.append(dict(worker_id=worker.id, worker_name=worker.name, eligible=not reasons, reasons=reasons))
    return dict(job_id=job.id, as_of=now, policy='registered-model' if job.model_id in MODEL_REGISTRY else 'legacy-model-match-only',
                workers=rows, limit=limit, offset=offset)
