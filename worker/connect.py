"""Validate a coordinator connection without exposing the token in command history."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--start-worker',action='store_true',help='Start compute on this machine after validation')
    parser.add_argument('--name',default=None)
    args=parser.parse_args()
    token=os.environ.get('API_TOKEN') or getpass.getpass('Coordinator API token (hidden): ')
    try:
        r=httpx.get(args.url.rstrip('/')+'/api/connection',headers={'Authorization':'Bearer '+token},timeout=10,follow_redirects=False)
        if r.status_code==401:
            print('Token rejected. Use the coordinator API_TOKEN.');return 1
        r.raise_for_status()
        data=r.json()
    except (httpx.HTTPError,ValueError):
        print('Cannot validate coordinator. Check the address, network, and backend version.');return 1
    print('Authenticated. Model:',data['model_id'])
    print('Heartbeat interval:',data['heartbeat_interval_seconds'],'seconds')
    if args.start_worker:
        os.environ['API_TOKEN']=token
        command=[sys.executable,str(Path(__file__).with_name('run.py')),'--url',args.url]
        if args.name:command+=['--name',args.name]
        os.execv(sys.executable,command)
    return 0

if __name__=='__main__':raise SystemExit(main())
