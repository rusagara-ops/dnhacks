import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import connect

class ConnectTests(unittest.TestCase):
    def check(self,status):
        response=httpx.Response(status,json={'model_id':'gemma3:12b','heartbeat_interval_seconds':5},request=httpx.Request('GET','http://test/api/connection'))
        output=io.StringIO()
        with patch.dict(os.environ,{'API_TOKEN':''}),patch.object(sys,'argv',['connect.py','--url','http://test']),patch.object(connect.getpass,'getpass',return_value='private-test-token'),patch.object(connect.httpx,'get',return_value=response) as get,contextlib.redirect_stdout(output):
            code=connect.main()
        self.assertNotIn('private-test-token',output.getvalue())
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'],'Bearer private-test-token')
        return code,output.getvalue()
    def test_connect(self):self.assertEqual(self.check(200)[0],0)
    def test_rejected_token(self):self.assertEqual(self.check(401)[0],1)

if __name__=='__main__':unittest.main()
