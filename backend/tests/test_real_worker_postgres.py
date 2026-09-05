"""Opt-in real Ollama model test using a temporary database schema."""
import os
import subprocess
from pathlib import Path
import pytest
from test_simulator_postgres import server, stop
from test_scheduler_postgres import factory

@pytest.mark.skipif(os.environ.get('RUN_REAL_MODEL_TEST')!='1',reason='Requires downloaded model and worker venv')
def test_real_summary_worker(server):
    url,c=server
    # The fixture owns a separate temporary schema; its app settings are patched by
    # the fixture below before the HTTP server starts.
    document = ('The city library will extend weekday closing time from 6 p.m. to 9 p.m. for a three-month pilot. Residents requested study space after work.\n\n'
                'Free Tuesday workshops will help residents prepare resumes and complete online job applications. Twelve computers are available.\n\n'
                'The city allocated $18,000 for extra staffing. Managers will track attendance and costs before the council decides whether to continue.')
    response=c.post('/api/jobs',json={'task_type':'summarization','inputs':[document]})
    assert response.status_code==201
    jid=response.json()['job_id']
    root=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if k not in ['DATABASE_URL','TEST_DATABASE_URL']}
    env['API_TOKEN']='sim-test'
    processes=[subprocess.Popen([str(root/'worker/.venv/bin/python'),str(root/'worker/run.py'),
        '--url',url,'--name',f'real-local-{i}','--max-tasks','1','--idle-timeout','60','--poll-seconds','0.2'],
        env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) for i in range(1)]
    try:
        for p in processes:
            output=p.communicate(timeout=600)[0]
            assert p.returncode==0,output
        result=c.get(f'/api/jobs/{jid}/results').json()
        assert result['status']=='COMPLETED' and result['completed_inputs']==1
        assert len({t['worker_id'] for t in result['tasks']})==1
        assert len(result['results'])==1 and result['results'][0]['text'].strip()
        assert '\n' not in result['results'][0]['text']
        registered=c.get('/api/workers').json()[0]
        assert registered['ram_gb'] > 0
        assert registered['ram_available_gb'] is not None
        print('REAL SUMMARY OUTPUTS:',[r['text'] for r in result['results']])
        assert c.get('/demo/').status_code==200
        assert c.get('/demo/app.js').status_code==200
    finally:
        for p in processes:stop(p)

@pytest.fixture(autouse=True)
def model_config(monkeypatch):
    import test_simulator_postgres as module
    import httpx
    models=httpx.get('http://127.0.0.1:11434/api/tags').json()['models']
    model=next(m for m in models if m['name']=='gemma3:12b')
    monkeypatch.setattr(module,'MODEL_ID','gemma3:12b')
    monkeypatch.setattr(module,'MODEL_REVISION',model['digest'])
