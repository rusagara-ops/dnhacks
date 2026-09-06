import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_scheduler_postgres import factory, seed, claim, SETTINGS
from app.models import Task, Worker
from app.schemas.job import JobCreateRequest
from app.schemas.task import TaskCompleteRequest
from app.services.job_service import create_job
from app.services.task_service import complete_task, job_results


def test_summary_contract_and_attribution(factory):
    worker = seed(factory)[0]
    with factory.begin() as db:
        db.get(Worker, worker).supported_tasks = ['summarization']
    with factory() as db:
        job = create_job(db, JobCreateRequest(task_type='summarization', inputs=['First paragraph','Second paragraph']),
                         SETTINGS.inference_model_id, SETTINGS.inference_model_revision)
        assert job.total_tasks == 2
    a = claim(factory,worker)
    assert len(a.inputs)==1
    wrong = TaskCompleteRequest(worker_id=worker,assignment_id=a.assignment_id,
        results=[{'index':a.inputs[0].index,'label':'POSITIVE','score':0.9}],execution_time_ms=3)
    with factory() as db, pytest.raises(HTTPException) as e:
        complete_task(db,a.task_id,wrong)
    assert e.value.status_code==422
    correct = TaskCompleteRequest(worker_id=worker,assignment_id=a.assignment_id,
        results=[{'index':a.inputs[0].index,'text':'A short summary.'}],execution_time_ms=3)
    with factory() as db: assert complete_task(db,a.task_id,correct).status=='completed'
    with factory() as db:
        result=job_results(db,job.id)
        assert result.completed_inputs==1 and not result.is_final
        assert result.results[0].text=='A short summary.'
        assert result.tasks[0].worker_id==worker and result.tasks[0].worker_name
        assert result.tasks[0].execution_time_ms==3
        assert result.tasks[1].status=='QUEUED'
