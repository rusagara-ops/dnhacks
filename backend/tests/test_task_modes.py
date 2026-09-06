import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from test_scheduler_postgres import factory, seed, claim, SETTINGS
from app.models import Worker
from app.schemas.job import JobCreateRequest
from app.schemas.task import TaskCompleteRequest, ExtractionResult
from app.services.job_service import create_job
from app.services.task_service import complete_task, job_results


@pytest.mark.parametrize('mode,instruction,result',[
    ('document-qa','What is the budget?',{'text':'The budget is $18,000.'}),
    ('information-extraction',None,{'names':['Abel'],'dates':[],'amounts':['$18,000'],'action_items':[]}),
    ('coding-assistance','Explain the error.',{'text':'An empty list causes division by zero.\n```python\nreturn None\n```'})])
def test_mode_contract_persists(factory,mode,instruction,result):
    worker=seed(factory)[0]
    with factory.begin() as db: db.get(Worker,worker).supported_tasks=[mode]
    payload=JobCreateRequest(task_type=mode,inputs=['Source text'],instruction=instruction)
    with factory() as db: job=create_job(db,payload,SETTINGS.inference_model_id,SETTINGS.inference_model_revision)
    assignment=claim(factory,worker)
    assert assignment.instruction==instruction and assignment.task_type==mode
    if mode=='information-extraction':
        bad=TaskCompleteRequest(worker_id=worker,assignment_id=assignment.assignment_id,
            results=[{'index':0,'text':'Unstructured response'}],execution_time_ms=1)
        with factory() as db,pytest.raises(HTTPException): complete_task(db,assignment.task_id,bad)
    completion=TaskCompleteRequest(worker_id=worker,assignment_id=assignment.assignment_id,
        results=[{'index':0,**result}],execution_time_ms=2)
    with factory() as db: complete_task(db,assignment.task_id,completion)
    with factory() as db:
        stored=job_results(db,job.id)
        assert stored.status=='COMPLETED' and stored.results[0].model_dump()=={'index':0,**result}


@pytest.mark.parametrize('payload',[
    {'task_type':'document-qa','inputs':['Document']},
    {'task_type':'document-qa','inputs':['Document'],'instruction':'  '},
    {'task_type':'summarization','inputs':['Document'],'instruction':'Question'},
    {'task_type':'document-qa','inputs':['x'*6000],'instruction':'é'*300},
])
def test_invalid_mode_input(payload):
    with pytest.raises(ValidationError): JobCreateRequest(**payload)


def test_extraction_shape_is_bounded():
    with pytest.raises(ValidationError): ExtractionResult(index=0,names=['Name']*21,dates=[],amounts=[],action_items=[])
