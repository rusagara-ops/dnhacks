import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import run
from hardware import device_id,lock_worker


class ReconnectTests(unittest.TestCase):
    def test_stable_local_identity_and_process_lock(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'WORKER_STATE_DIR':directory}):
            self.assertEqual(device_id(),device_id())
            handle=lock_worker()
            try:
                with self.assertRaises(RuntimeError): lock_worker()
            finally: handle.close()

    def test_transient_pull_failure_retries_without_reregister(self):
        counts={'register':0,'pull':0}
        def handler(request):
            if request.url.path.endswith('/register'):
                counts['register']+=1
                return httpx.Response(201,json={'worker_id':'test','heartbeat_interval_seconds':1})
            if request.url.path.endswith('/heartbeat'): return httpx.Response(200,json={'status':'ok'})
            counts['pull']+=1
            if counts['pull']==1: raise httpx.ReadTimeout('temporary')
            if counts['pull']==2:return httpx.Response(503)
            return httpx.Response(200,json={'task':None})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test')
        fake=SimpleNamespace(model_id='gemma3:12b',model_revision='digest',gpu_memory_gb=lambda:1)
        args=SimpleNamespace(url='http://test',name='test',max_tasks=1,idle_timeout=.001,poll_seconds=.01)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'WORKER_STATE_DIR':directory}), \
             patch.object(run,'Summarizer',return_value=fake),patch.object(run,'hardware',return_value={}), \
             patch.object(run.httpx,'AsyncClient',return_value=client):
            self.assertEqual(asyncio.run(run.run(args)),0)
        self.assertEqual(counts,{'register':1,'pull':3})

if __name__=='__main__':unittest.main()
