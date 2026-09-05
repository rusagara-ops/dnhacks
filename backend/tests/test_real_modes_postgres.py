"""Opt-in GPU inference through HTTP and an isolated PostgreSQL schema."""
import os
from pathlib import Path
import subprocess
import pytest
from test_scheduler_postgres import factory
from test_simulator_postgres import server,stop
from test_real_worker_postgres import model_config

@pytest.mark.skipif(os.environ.get('RUN_REAL_MODEL_TEST')!='1',reason='Requires local Ollama GPU model')
def test_real_modes(server):
    url,client=server
    document='Abel will send the project report to Kevin by September 8, 2026. The approved budget is $18,000.'
    cases=[
        ('document-qa',document,'What is the approved budget?'),
        ('document-qa',document,'What is the office street address?'),
        ('information-extraction',document,None),
        ('coding-assistance','def average(values):\n    return sum(values) / len(values)\n\nprint(average([]))','Why does this fail on an empty list? Suggest a short fix.')]
    jobs=[]
    for mode,source,instruction in cases:
        response=client.post('/api/jobs',json={'task_type':mode,'inputs':[source],**({'instruction':instruction} if instruction else {})})
        assert response.status_code==201,response.text
        jobs.append(response.json()['job_id'])
    root=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if k not in ['DATABASE_URL','TEST_DATABASE_URL']};env['API_TOKEN']='sim-test'
    process=subprocess.Popen([str(root/'worker/.venv/bin/python'),str(root/'worker/run.py'),'--url',url,
        '--name','Gemma-Feature-Test','--max-tasks','4','--idle-timeout','60','--poll-seconds','0.2'],
        env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        output=process.communicate(timeout=600)[0]
        assert process.returncode==0,output
        results=[]
        for jid in jobs:
            response=client.get(f'/api/jobs/{jid}/results');response.raise_for_status();result=response.json()
            assert result['status']=='COMPLETED',result
            results.append(result['results'][0])
        assert '18,000' in results[0]['text']
        assert set(results[2])=={'index','names','dates','amounts','action_items'}
        assert '$18,000' in results[2]['amounts']
        assert 'Abel' in results[2]['names'] and 'Kevin' in results[2]['names']
        assert '\n' in results[3]['text']
        for case,result in zip(cases,results): print(case[0],result)
    finally: stop(process)
