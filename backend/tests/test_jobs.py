from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.db.database import get_db
from app.main import create_app
from app.schemas.job import JobCreateRequest
from app.services.job_service import split_into_tasks


@pytest.mark.parametrize('count,sizes', [(1,[1]),(25,[25]),(26,[25,1]),(100,[25]*4),(1000,[25]*40)])
def test_chunking(count,sizes):
    inputs=[f' review {i} ' for i in range(count)]
    chunks=list(split_into_tasks(inputs))
    assert [c['input_count'] for c in chunks]==sizes
    flattened=[item for chunk in chunks for item in chunk['payload']['inputs']]
    assert flattened==[{'index':i,'text':value} for i,value in enumerate(inputs)]


@pytest.mark.parametrize('changes', [
    {'inputs':[]}, {'inputs':[' ']}, {'inputs':['x']*1001}, {'inputs':['x'*10001]},
    {'inputs':['é'*1000]*501}, {'task_type':'unknown'}, {'optimization':'cheapest'}, {'extra':True},
])
def test_invalid_jobs(changes):
    with pytest.raises(ValidationError):
        JobCreateRequest(**({'task_type':'sentiment-classification','inputs':['hello']} | changes))


def test_job_http_contract():
    app=create_app(Settings(_env_file=None,database_url=None,api_token='test'))
    session=MagicMock(); session.get.return_value=None
    app.dependency_overrides[get_db]=lambda: session
    with TestClient(app) as client:
        assert client.post('/api/jobs',json={}).status_code==401
        client.headers['Authorization']='Bearer test'
        assert client.post('/api/jobs',json={'task_type':'sentiment-classification','inputs':[]}).status_code==422
        assert client.get('/api/jobs/not-a-uuid').status_code==422
        assert client.get('/api/jobs/'+str(uuid4())).status_code==404
        assert client.get('/api/jobs?limit=501').status_code==422
        assert client.get('/api/jobs?offset=-1').status_code==422
