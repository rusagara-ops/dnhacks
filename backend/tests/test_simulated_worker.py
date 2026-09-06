import argparse
import asyncio
import json
import httpx
from scripts import simulated_worker


def test_offline_pull_and_ambiguous_upload_retries(monkeypatch):
    completions=[]; pulls=[]
    def respond(request):
        path=request.url.path
        if path.endswith('/register'):
            return httpx.Response(201,json={'worker_id':'test-worker','heartbeat_interval_seconds':99})
        if path.endswith('/heartbeat'):
            return httpx.Response(200,json={'status':'ok'})
        if path.endswith('/next-task'):
            pulls.append(1)
            if len(pulls)==1:return httpx.Response(409,json={'detail':'Worker is offline'})
            return httpx.Response(200,json={'task':{
                'task_id':'task','job_id':'job','assignment_id':'assignment',
                'model_id':simulated_worker.MODEL_ID,'model_revision':simulated_worker.MODEL_REVISION,
                'inputs':[{'index':0,'text':'fake'}]}})
        if path.endswith('/complete'):
            completions.append(json.loads(request.content))
            return httpx.Response(503 if len(completions)==1 else 200,json={'status':'completed'})
        raise AssertionError(path)
    original=httpx.AsyncClient
    monkeypatch.setattr(simulated_worker.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    monkeypatch.setenv('API_TOKEN','fake-test-token')
    args=argparse.Namespace(url='http://test',name='test',max_tasks=1,delay=0.001,poll_seconds=0.001,
                            idle_timeout=10,crash_after_claim=False,fail_tasks=False)
    assert asyncio.run(simulated_worker.run(args))==0
    assert len(pulls)==2 and len(completions)==2
    assert completions[0]==completions[1]
    assert completions[0]['results']==[{'index':0,'label':'POSITIVE','score':0.5}]


def test_ui_fixtures_match_result_contracts_and_preserve_indexes():
    from app.schemas.task import GeneratedText, ExtractionResult
    for mode in ['summarization', 'document-qa', 'coding-assistance', 'information-extraction']:
        results = simulated_worker.predictions({'task_type': mode, 'inputs': [{'index': 25, 'text': 'test'}]})
        schema = ExtractionResult if mode == 'information-extraction' else GeneratedText
        validated = schema.model_validate(results[0])
        assert validated.index == 25
        assert 'SIMULATION' in str(results[0])
