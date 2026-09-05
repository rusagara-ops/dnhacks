from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.task import TaskCompleteRequest
from app.schemas.worker import HeartbeatRequest


@pytest.mark.parametrize('prediction', [
    {'index':0,'label':'OTHER','score':0.5},
    {'index':0,'label':'POSITIVE','score':1.1},
    {'index':-1,'label':'POSITIVE','score':0.5},
    {'index':0,'label':'POSITIVE','score':float('nan')},
])
def test_reject_invalid_predictions(prediction):
    with pytest.raises(ValidationError):
        TaskCompleteRequest(worker_id=uuid4(),assignment_id=uuid4(),results=[prediction],execution_time_ms=1)


@pytest.mark.parametrize('extras', [
    {'task_id':uuid4()}, {'assignment_id':uuid4()},
    {'task_id':uuid4(),'assignment_id':uuid4(),'active_tasks':0},
])
def test_heartbeat_assignment_pair(extras):
    with pytest.raises(ValidationError):
        HeartbeatRequest(**({'cpu_utilization':0,'memory_utilization':0,'active_tasks':1}|extras))
