"""Consumer-visible cache/gate/order/settlement behavior; model I/O is an explicit fixture."""
import asyncio,json,hashlib
import httpx
import gateway

BODY={'model':'lab-qwen','messages':[{'role':'user','content':'hello'}],'stream':True,'max_tokens':16}

class Fixture:
 def __init__(self,text='OK',finish='stop',usage=True):self.text=text;self.finish=finish;self.measured=usage;self.calls=[]
 async def generate(self,body,request_id,attempt_id,emit):
  self.calls.append((body,request_id,attempt_id));emit('backend_first_content')
  return gateway.BackendResult(self.text,self.finish,{'prompt_tokens':7,'completion_tokens':2,'total_tokens':9} if self.measured else None,'fixture-sse',200)


def setup(tmp_path,**kw):
 backend=Fixture(**kw)
 app=gateway.create_app(gateway.Config(log_path=tmp_path/'gw.jsonl',active_limit=1,queue_limit=1),backend,lambda messages:list(messages[-1]['content'].encode()))
 return app,backend

async def post(app,body=None,token='lab-a',**headers):
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://lab') as c:
  return await c.post('/v1/chat/completions',json=BODY if body is None else body,headers={'Authorization':'Bearer '+token,**headers})

def rows(tmp_path):return [json.loads(x) for x in (tmp_path/'gw.jsonl').read_text().splitlines()]

def content(response):
 vals=[json.loads(x[6:]) for x in response.text.splitlines() if x.startswith('data: {')]
 return ''.join(x['choices'][0]['delta'].get('content','') for x in vals if x.get('choices'))


def test_auth_and_capability_rejections_never_generate_or_hit_cache(tmp_path):
 async def run():
  app,b=setup(tmp_path)
  assert (await post(app,token='bad')).status_code==401
  for patch in ({'tools':[]},{'stream':False},{'model':'unknown'},{'max_tokens':True},{'messages':[{'role':'user','content':[{'type':'text','text':'hello'}]}]}):
   assert (await post(app,{**BODY,**patch})).status_code==400
  assert not b.calls
  assert all(r['attempts']==[] for r in rows(tmp_path))
  assert len(rows(tmp_path))==6
 asyncio.run(run())


def test_cache_is_tenant_scoped_and_keeps_original_usage_separate(tmp_path):
 async def run():
  app,b=setup(tmp_path)
  a1=await post(app);a2=await post(app);b1=await post(app,token='lab-b');spoof=await post(app,**{'X-Tenant-Id':'tenant-b'})
  assert all(r.status_code==200 and content(r)=='OK' for r in (a1,a2,b1,spoof))
  assert len(b.calls)==2
  led=rows(tmp_path)
  assert [x['cache'] for x in led]==['miss','hit','miss','hit']
  assert [x['tenant_id'] for x in led]==['tenant-a','tenant-a','tenant-b','tenant-a']
  assert led[1]['generation_usage']=={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
  assert led[1]['cache_origin_usage']['total_tokens']==9 and led[1]['attempts']==[]
 asyncio.run(run())


def test_policy_or_identity_change_cannot_reuse_old_response(tmp_path):
 async def run():
  app,b=setup(tmp_path);await post(app)
  app.state.gateway.policy_version='rule-v2';await post(app)
  app.state.gateway.identity={**app.state.gateway.identity,'model_fingerprint':'new-weights'};await post(app)
  app.state.gateway.identity={**app.state.gateway.identity,'template_sha256':'new-template'};await post(app)
  assert len(b.calls)==4 and all(r['cache']=='miss' for r in rows(tmp_path))
 asyncio.run(run())


def test_token_budget_and_unsupported_fields_are_checked_before_cache(tmp_path):
 async def run():
  app,b=setup(tmp_path);await post(app)
  assert (await post(app,{**BODY,'messages':[{'role':'user','content':'x'*600}]})).status_code==400
  assert (await post(app,{**BODY,'seed':999})).status_code==400
  assert len(b.calls)==1
 asyncio.run(run())


def test_output_review_blocks_delivery_but_preserves_real_attempt_cost(tmp_path):
 async def run():
  app,b=setup(tmp_path,text='LAB_BLOCK')
  a=await post(app);second=await post(app)
  assert a.status_code==422 and 'LAB_BLOCK' not in a.text
  assert second.status_code==422 and len(b.calls)==2
  for r in rows(tmp_path):
   assert r['terminal']=='review_rejected' and r['gateway_emitted_utf8_bytes']==0
   assert r['generation_usage']['total_tokens']==9 and len(r['attempts'])==1
 asyncio.run(run())


def test_length_or_missing_usage_cannot_seed_complete_measured_cache(tmp_path):
 async def run():
  for i,settings in enumerate(({'finish':'length'},{'usage':False})):
   d=tmp_path/str(i);d.mkdir();app,b=setup(d,**settings)
   await post(app);await post(app)
   assert len(b.calls)==2
   if i==1:assert all(x['generation_usage'] is None for x in rows(d))
 asyncio.run(run())


def test_bounded_admission_refuses_overflow_and_releases_after_failure(tmp_path):
 class Slow(Fixture):
  def __init__(self):super().__init__();self.enter=asyncio.Event();self.release=asyncio.Event()
  async def generate(self,*args):
   self.enter.set();await self.release.wait();raise RuntimeError('controlled backend failure')
 async def run():
  app,_=setup(tmp_path);b=Slow();app.state.gateway.backend=b
  first=asyncio.create_task(post(app));await b.enter.wait()
  second=asyncio.create_task(post(app));await asyncio.sleep(.01)
  overflow=await post(app);assert overflow.status_code==429
  b.release.set();await asyncio.gather(first,second)
  assert app.state.gateway.admission.reserved==0
  assert len(rows(tmp_path))==3
  assert sum(x['terminal']=='admission_rejected' for x in rows(tmp_path))==1
 asyncio.run(run())


def test_stream_content_sent_only_after_complete_review_and_terminal_reconciles(tmp_path):
 async def run():
  app,b=setup(tmp_path);r=await post(app);record=rows(tmp_path)[0]
  assert r.text.endswith('data: [DONE]\n\n')
  events=[x['event'] for x in record['events']]
  assert events.index('capability_accepted')<events.index('cache_miss')<events.index('admission_entered')<events.index('backend_first_content')<events.index('review_allowed')<events.index('client_first_content')<events.index('terminal')
  assert record['gateway_emitted_utf8_bytes']==2 and record['gateway_emitted_sha256']==hashlib.sha256(b'OK').hexdigest()
  assert record['attempts'][0]['attempt_id']!=record['request_id']
 asyncio.run(run())


def test_backend_failure_has_completed_attempt_ledger_before_terminal(tmp_path):
 class Failed(Fixture):
  async def generate(self,*args):raise RuntimeError('injected')
 async def run():
  app,_=setup(tmp_path);app.state.gateway.backend=Failed()
  assert (await post(app)).status_code==502
  record=rows(tmp_path)[0];a=record['attempts'][0]
  assert a['ended_ns']>=a['started_ns'] and record['generation_usage'] is None
  assert record['ended_ns']>=a['ended_ns']
 asyncio.run(run())


def test_reviewed_cache_hit_bypasses_saturated_generation_admission(tmp_path):
 class Held(Fixture):
  def __init__(self):super().__init__();self.enter=asyncio.Event();self.release=asyncio.Event()
  async def generate(self,body,*args):
   if body['messages'][-1]['content']=='hold':self.enter.set();await self.release.wait()
   return await super().generate(body,*args)
 async def run():
  app,_=setup(tmp_path);b=Held();app.state.gateway.backend=b
  await post(app)
  held=asyncio.create_task(post(app,{**BODY,'messages':[{'role':'user','content':'hold'}]}))
  await b.enter.wait();hit=await post(app)
  assert hit.status_code==200 and hit.headers['X-Lab-Cache']=='hit'
  b.release.set();await held
 asyncio.run(run())


def test_cache_expiration_and_entry_bound_preserve_miss_semantics(tmp_path):
 async def run():
  app,b=setup(tmp_path);app.state.gateway.cfg.cache_entries=1
  await post(app);await post(app,{**BODY,'messages':[{'role':'user','content':'other'}]});await post(app)
  assert len(b.calls)==3 and len(app.state.gateway.cache)==1
  for entry in app.state.gateway.cache.values():entry['stored_at']-=301
  await post(app);assert len(b.calls)==4
 asyncio.run(run())


def test_terminal_clock_contains_last_recorded_event(tmp_path):
 async def run():
  app,_=setup(tmp_path);await post(app)
  r=rows(tmp_path)[0];assert r['started_ns']<=r['events'][0]['monotonic_ns'] and r['ended_ns']>=r['events'][-1]['monotonic_ns']
 asyncio.run(run())
