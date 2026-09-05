"""Opt-in real model test: two processes on this computer, not two physical Macs."""
import os
import subprocess
from pathlib import Path
import pytest
from test_simulator_postgres import server, stop
from test_scheduler_postgres import factory

@pytest.mark.skipif(os.environ.get('RUN_REAL_MODEL_TEST')!='1',reason='Requires downloaded model and worker venv')
def test_two_real_summary_workers(server):
    url,c=server
    # The fixture owns a separate temporary schema; its app settings are patched by
    # the fixture below before the HTTP server starts.
    response=c.post('/api/jobs',json={'task_type':'summarization','inputs':[
        'A school installed solar panels to supply half of its electricity. Students will study their energy readings.',
        'The rail service added two morning trains to reduce overcrowding on its busiest route.',
        'A bakery donates unsold bread to a food bank every evening. Volunteers collect the bread after closing.',
        'The museum now offers free admission on Sunday mornings to welcome more local families.'
    ]})
    assert response.status_code==201
    jid=response.json()['job_id']
    root=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if k not in ['DATABASE_URL','TEST_DATABASE_URL']}
    env['API_TOKEN']='sim-test'
    processes=[subprocess.Popen([str(root/'worker/.venv/bin/python'),str(root/'worker/run.py'),
        '--url',url,'--name',f'real-local-{i}','--max-tasks','2','--idle-timeout','60','--poll-seconds','0.2'],
        env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) for i in range(2)]
    try:
        for p in processes:
            output=p.communicate(timeout=180)[0]
            assert p.returncode==0,output
        result=c.get(f'/api/jobs/{jid}/results').json()
        assert result['status']=='COMPLETED' and result['completed_inputs']==4
        assert len({t['worker_id'] for t in result['tasks']})==2
        assert all(r['text'].strip() for r in result['results'])
        print('REAL SUMMARY OUTPUTS:',[r['text'] for r in result['results']])
        assert c.get('/demo/').status_code==200
        assert c.get('/demo/app.js').status_code==200
    finally:
        for p in processes:stop(p)

@pytest.fixture(autouse=True)
def model_config(monkeypatch):
    import test_simulator_postgres as module
    monkeypatch.setattr(module,'MODEL_ID','Qwen/Qwen2.5-0.5B-Instruct')
    monkeypatch.setattr(module,'MODEL_REVISION','7ae557604adf67be50417f59c2c2f167def9a775')
