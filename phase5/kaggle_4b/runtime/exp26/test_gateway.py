import asyncio
import pytest
from gateway import can_retry, Settlements, Gateway, make_plan

@pytest.mark.parametrize('committed,key,retryable,count,expected',[(False,'k',True,1,True),(True,'k',True,1,False),(False,None,True,1,False),(False,'k',False,1,False),(False,'k',True,2,False)])
def test_retry_boundary(committed,key,retryable,count,expected):
 assert can_retry(committed,key,retryable,count)==expected

def test_settlement_idempotent_and_conflicts():
 s=Settlements();assert s.add('a',None);assert not s.add('a',None)
 with pytest.raises(ValueError):s.add('a',{'total_tokens':3})
 assert s.rows=={'a':None}

def run_case(name,disconnect=False):
 async def run():
  cfg=next(x for x in make_plan()['cases'] if x['case_id']==name)
  g=Gateway([cfg]);received=[];rx=asyncio.Queue()
  await rx.put({'type':'http.request','body':('{"case_id":"'+name+'"}').encode(),'more_body':False})
  async def send(m):
   received.append(m)
   if disconnect and b'"content"' in m.get('body',b''):await rx.put({'type':'http.disconnect'})
  await g({'type':'http','path':'/generate','method':'POST'},rx.get,send)
  return g.records,received,g
 return asyncio.run(run())

@pytest.mark.parametrize('name', ['unconnected-retry','pre-timeout-retry','post-break','review-reject','review-unavailable','cancel-late','stale-generation','drain-graceful','drain-timeout','drain-reject','no-key','duplicate-settlement'])
def test_frozen_case_lifecycle(name):
 records,messages,g=run_case(name)
 assert len(records)==1
 r=records[0];c=g.cases[name]
 assert r['terminal']==c['terminal']
 assert len(r['attempts'])==c['attempts']
 assert not g.active and g.worker_count==0
 assert len(g.settlements.rows)==c['attempts']
 assert all(a['worker_joined'] for a in r['attempts'])
 assert all(not e.get('after_stop') for e in r['events'] if e['event']=='content_sent')
 if name=='post-break':assert r['committed'] and len(r['attempts'])==1
 if name in ('cancel-late','stale-generation'):assert any(e['event']=='late_discard' for e in r['events'])

def test_real_disconnect_on_controlled_stream():
 records,messages,g=run_case('drain-graceful',disconnect=True)
 assert records[0]['terminal']=='client_disconnected'
 assert not g.active and g.worker_count==0
