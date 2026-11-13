import asyncio,json
import pytest
from gateway import Gateway
from plan import make_plan

async def request(g,c,token=None):
 q=asyncio.Queue();await q.put({'type':'http.request','body':json.dumps({'case_id':c['case_id'],**c['body']}).encode(),'more_body':False});messages=[]
 async def send(m):messages.append(m)
 await g({'type':'http','method':'POST','path':'/'+c['route'],'headers':[(b'authorization',('Bearer '+(token or c['token'])).encode())]},q.get,send)
 return g.records[-1],messages

def test_full_plan_fixed_denominators():
 p=make_plan();assert len(p['cases'])==42 and p['quality']['eligible_requests']==37

def test_fault_targets_start_with_empty_response_cache():
 p=make_plan()
 for name in ['break-after-commit','client-cancel','drain-running']:
  step=next(s for s in p['steps'] if name in s['cases'])
  assert step.get('clear_cache')

def test_lifecycle_native_headers_use_current_experiment():
 import httpx
 from unittest.mock import patch
 async def run():
  captured=[]
  def serve(req):
   captured.append(req)
   raw='data: '+json.dumps({'choices':[{'delta':{'content':'7'},'finish_reason':'stop'}]})+'\n\n'
   raw+='data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}})+'\n\ndata: [DONE]\n\n'
   return httpx.Response(200,content=raw)
  p=make_plan();g=Gateway(p,encoder=lambda m:[1]);original=httpx.AsyncClient
  with patch('lifecycle.httpx.AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(serve))):
   await request(g,p['cases'][0])
  assert captured[0].headers['X-Exp27-Request-ID']==p['cases'][0]['request_id']
  assert captured[0].headers['X-Exp27-Attempt-ID'].endswith('/a1')
 asyncio.run(run())

def test_request_end_contains_last_event():
 async def run():
  p=make_plan();g=Gateway(p,encoder=lambda m:[1],native_source=Fixture())
  r,_=await request(g,p['cases'][1])
  assert all(r['started_ns']<=e['ns']<=r['ended_ns'] for e in r['events'])
 asyncio.run(run())

class Fixture:
 async def __call__(self,c,a,fault):
  a['backend_body']=c['backend_body'];a['backend_body_sha256']='fixture'
  yield {'kind':'content','text':'7'}
  yield {'kind':'finish','finish':'stop'}
  yield {'kind':'usage','usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}}


def test_cache_identity_and_origin_never_charge_second_generation():
 async def run():
  p=make_plan();g=Gateway(p,encoder=lambda m:[1],native_source=Fixture())
  cold=p['cases'][1];warm=p['cases'][2]
  r,_=await request(g,cold);hit,_=await request(g,warm)
  assert r['cache']=='miss' and len(r['attempts'])==1
  assert hit['cache']=='hit' and hit['attempts']==[] and hit['settlements']==[]
  assert hit['cache_origin']['request_id']==r['request_id'] and hit['cache_origin']['usage']['total_tokens']==5
  assert not g.admission.reserved and g.base.worker_count==0
 asyncio.run(run())

@pytest.mark.parametrize('name,terminal',[('reject-auth','authentication_rejected'),('reject-tools','capability_rejected'),('reject-budget','budget_rejected')])
def test_entry_refusals_have_no_attempt(name,terminal):
 async def run():
  p=make_plan();g=Gateway(p,encoder=lambda m:list(range(900 if name=='reject-budget' else 1)),native_source=Fixture())
  c=next(c for c in p['cases'] if c['case_id']==name);r,_=await request(g,c)
  assert r['terminal']==terminal and not r['attempts']
 asyncio.run(run())

def test_gate_retains_usage_and_does_not_send_blocked_text():
 class Block(Fixture):
  async def __call__(self,c,a,f):
   async for x in super().__call__(c,a,f):
    if x['kind']=='content':x={'kind':'content','text':'LAB_BLOCK'}
    yield x
 async def run():
  p=make_plan();g=Gateway(p,encoder=lambda m:[1],native_source=Block());r,m=await request(g,p['cases'][1])
  assert r['terminal']=='review_rejected' and r['sent_content']==''
  assert r['settlements'][0]['usage']['total_tokens']==5
  assert not g.cache
 asyncio.run(run())
