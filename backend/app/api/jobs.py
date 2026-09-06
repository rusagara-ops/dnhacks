import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models import Job
from app.schemas.job import JobCreateRequest, JobCreateResponse, JobResponse
from app.services import job_service
from app.core.model_registry import select_model
from app.schemas.task import JobResultResponse
from app.services.task_service import job_results

router = APIRouter(prefix='/jobs', tags=['jobs'])
logger = logging.getLogger(__name__)


@router.post('', status_code=201, response_model=JobCreateResponse)
def create_job(payload: JobCreateRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    model_id, revision = select_model(payload, request.app.state.settings)
    job = job_service.create_job(db, payload, model_id, revision,
                                request.app.state.settings.worker_timeout_seconds)
    response.headers['Location'] = f'/api/jobs/{job.id}'
    logger.info('Job created: %s (%s tasks)', job.id, job.total_tasks)
    return JobCreateResponse(job_id=job.id, total_inputs=job.total_inputs, total_tasks=job.total_tasks)


@router.get('', response_model=list[JobResponse])
def list_jobs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return job_service.list_jobs(db, limit, offset)


@router.get('/{job_id}', response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    return job_service.describe_job(job)


@router.get('/{job_id}/results', response_model=JobResultResponse)
def results(job_id: UUID, db: Session = Depends(get_db)):
    return job_results(db, job_id)
