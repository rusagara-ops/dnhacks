from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.model_registry import MODEL_REGISTRY
from app.db.database import get_db
from app.models import Job, Worker
from app.services.eligibility import eligibility_reasons

router = APIRouter(tags=['inference awareness'])


@router.get('/models')
def models(request: Request):
    settings = request.app.state.settings
    return [dict(**spec.describe(), configured=(key == settings.inference_model_id and bool(settings.inference_model_revision)),
                 model_revision=settings.inference_model_revision if key == settings.inference_model_id else None)
            for key, spec in MODEL_REGISTRY.items()]


@router.get('/jobs/{job_id}/eligibility')
def job_eligibility(job_id: UUID, request: Request, limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    now = db.scalar(select(func.clock_timestamp()))
    workers = db.scalars(select(Worker).order_by(Worker.created_at.desc(), Worker.id).limit(limit).offset(offset))
    rows = []
    for worker in workers:
        reasons = eligibility_reasons(worker, job.model_id, job.model_revision, job.task_type,
                                      now, request.app.state.settings.worker_timeout_seconds)
        rows.append(dict(worker_id=worker.id, worker_name=worker.name, eligible=not reasons, reasons=reasons))
    return dict(job_id=job.id, as_of=now, policy='registered-model' if job.model_id in MODEL_REGISTRY else 'legacy-model-match-only',
                workers=rows, limit=limit, offset=offset)
