import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'worker'))
import inference
import httpx
import pytest
from app.schemas.job import JobCreateRequest
from pydantic import ValidationError


def setup(monkeypatch,content='The library extends its hours.',reason='stop'):
    calls=[]
    def get(url,**kwargs):
        data={'models':[{'name':inference.MODEL_ID,'digest':'abc','size_vram':8*1024**3}]}
        return httpx.Response(200,json=data,request=httpx.Request('GET',url))
    def post(url,**kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200,json={'done':True,'done_reason':reason,'message':{'content':content}},request=httpx.Request('POST',url))
    monkeypatch.setattr(inference.httpx,'get',get)
    monkeypatch.setattr(inference.httpx,'post',post)
    return inference.Summarizer(), calls


def task(text='First paragraph.\n\nSecond paragraph.'):
    return {'model_id':inference.MODEL_ID,'model_revision':'abc','task_type':'summarization',
            'inputs':[{'index':2,'text':text}]}


def test_whole_document_prompt_and_telemetry(monkeypatch):
    model,calls=setup(monkeypatch)
    assert model.predict(task())==[{'index':2,'text':'The library extends its hours.'}]
    assert calls[-1]['messages'][-1]['content']=='First paragraph.\n\nSecond paragraph.'
    assert calls[-1]['options']['num_ctx']==8192
    assert model.gpu_memory_gb()==8


def test_rejects_incomplete_generation(monkeypatch):
    model,_=setup(monkeypatch,reason='length')
    with pytest.raises(RuntimeError): model.predict(task())


def test_rejects_wrong_revision(monkeypatch):
    model,_=setup(monkeypatch)
    with pytest.raises(ValueError): model.predict(task()|{'model_revision':'wrong'})


def test_summary_byte_limit():
    with pytest.raises(ValidationError):
        JobCreateRequest(task_type='summarization',inputs=['é'*3001])
    assert JobCreateRequest(task_type='summarization',inputs=['A\n\nB']).inputs==['A\n\nB']


def test_cpu_only_ollama_does_not_register(monkeypatch):
    monkeypatch.setattr(inference.Summarizer,'gpu_memory_gb',lambda self:0)
    with pytest.raises(RuntimeError,match='GPU allocation'):
        setup(monkeypatch)
