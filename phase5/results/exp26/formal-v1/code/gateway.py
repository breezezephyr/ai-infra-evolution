"""Isolated exp26 ASGI lab. Text only, one GPU, controlled logical failover."""
import asyncio,hashlib,json,os,time,codecs
from pathlib import Path
import httpx

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def can_retry(committed,key,retryable,count):return not committed and bool(key) and retryable and count<2

class Settlements:
 def __init__(self):self.rows={}
 def add(self,aid,usage):
  if aid in self.rows:
   if self.rows[aid]!=usage:raise ValueError('conflicting settlement')
   return False
  self.rows[aid]=usage;return True

class Fault(Exception):
 def __init__(self,reason,retryable=False):self.reason=reason;self.retryable=retryable

def make_plan():
 cases=[]
 def add(name,terminal,attempts=1,mode='controlled',**kw):
  cases.append(dict(case_id=name,request_id='exp26-'+name,generation_id='g0',idempotency_key='safe-text-'+name,
    terminal=terminal,attempts=attempts,mode=mode,faults=[],control=None,**kw))
 add('unconnected-retry','completed',2);cases[-1]['faults']=['unconnected',None]
 add('pre-timeout-retry','completed',2);cases[-1]['faults']=['pre_timeout',None]
 add('post-break','backend_error');cases[-1]['faults']=['post_break']
 add('review-reject','review_rejected');cases[-1]['review']='reject'
 add('review-unavailable','review_unavailable');cases[-1]['review']='unavailable'
 add('cancel-late','cancelled');cases[-1]['control']='cancel';cases[-1]['late']=True
 add('stale-generation','superseded');cases[-1]['control']='supersede';cases[-1]['late']=True
 add('drain-graceful','completed');cases[-1]['control']='drain_graceful'
 add('drain-timeout','drain_timeout');cases[-1]['control']='drain_timeout'
 add('drain-reject','draining',0);cases[-1]['pre_draining']=True
 add('no-key','backend_error');cases[-1].update(faults=['unconnected'],idempotency_key=None)
 add('duplicate-settlement','completed');cases[-1]['duplicate_settlement']=True
 add('gpu-normal','completed',mode='gpu')
 add('gpu-pre-retry','completed',2,mode='gpu');cases[-1]['faults']=['pre_timeout',None]
 add('gpu-post-break','backend_error',mode='gpu');cases[-1]['faults']=['post_break']
 add('gpu-disconnect','client_disconnected',mode='gpu');cases[-1]['client_disconnect']=True
 add('gpu-drain-timeout','drain_timeout',mode='gpu');cases[-1]['control']='drain_timeout'
 return {'schema':1,'experiment':'exp26','scope':'single physical GPU; controlled faults, not natural HA failures; text only; in-memory settlement',
  'backend_port':8026,'gateway_port':8126,'cases':cases,'source_sha256':{}}

class Gateway:
 def __init__(self,cases,log_path=None,backend='http://127.0.0.1:8026'):
  self.cases={c['case_id']:c for c in cases};self.log_path=Path(log_path) if log_path else None
  self.backend=backend;self.records=[];self.active={};self.seen=set();self.draining=False
  self.worker_count=0;self.settlements=Settlements();self.clock_domain=f'gateway-{os.getpid()}'
 def save(self,r):
  self.records.append(r)
  if self.log_path:
   with self.log_path.open('a') as f:f.write(json.dumps(r,ensure_ascii=False)+'\n')
 async def drain(self,deadline):
  self.draining=True
  until=time.monotonic()+deadline
  while self.active and time.monotonic()<until:await asyncio.sleep(.002)
  for r in list(self.active.values()):r['signal']('drain_timeout')

 async def __call__(self,scope,receive,send):
  if scope['type']!='http':return
  async def reply(status,obj):
   headers=[(b'content-type',b'application/json')]
   if obj.get('request_id'):headers.append((b'x-request-id',obj['request_id'].encode()))
   await send({'type':'http.response.start','status':status,'headers':headers})
   await send({'type':'http.response.body','body':canonical(obj)})
  if scope['path']=='/health':
   return await reply(200,{'active':len(self.active),'workers':self.worker_count,'draining':self.draining,'settlements':len(self.settlements.rows)})
  if scope['path']=='/lab/reset' and scope['method']=='POST':
   if self.active or self.worker_count:return await reply(409,{'error':'not idle'})
   self.draining=False
   return await reply(200,{'reset':True})
  body=bytearray()
  while True:
   m=await receive()
   if m['type']=='http.disconnect':return
   body.extend(m.get('body',b''))
   if not m.get('more_body'):break
  try:c=self.cases[json.loads(body)['case_id']]
  except (KeyError,ValueError):return await reply(400,{'error':'unknown frozen case'})
  rid=c['request_id']
  if rid in self.seen:return await reply(409,{'error':'duplicate request'})
  self.seen.add(rid)
  r={'request_id':rid,'case_id':c['case_id'],'generation_id':c['generation_id'],'mode':c['mode'],
     'clock_domain':self.clock_domain,'started_ns':time.monotonic_ns(),'events':[],'attempts':[],'committed':False,
     'sent_content':'','terminal':None,'settlements':[],'idempotency_key':c['idempotency_key']}
  def event(name,**kw):r['events'].append({'event':name,'ns':time.monotonic_ns(),**kw})
  stop=asyncio.Event();first=asyncio.Event();reason=None
  def signal(value):
   nonlocal reason
   if reason is None:reason=value;event('stop_requested',reason=value);stop.set()
  if c.get('pre_draining'):self.draining=True
  if self.draining:
   r.update(terminal='draining',ended_ns=time.monotonic_ns());event('rejected_draining');self.save(r)
   return await reply(503,{'request_id':rid,'error':'draining'})
  self.active[rid]={'signal':signal}
  await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'text/event-stream'),(b'x-request-id',rid.encode())]})
  async def watch():
   while True:
    m=await receive()
    if m['type']=='http.disconnect':signal('client_disconnected');return
  async def control():
   await first.wait();action=c.get('control')
   if action=='cancel':signal('cancelled')
   elif action=='supersede':signal('superseded')
   elif action=='drain_timeout':await self.drain(.01)
   elif action=='drain_graceful':await self.drain(.3)
  watcher=asyncio.create_task(watch());controller=asyncio.create_task(control()) if c.get('control') else None
  async def packet(obj):await send({'type':'http.response.body','body':b'data: '+canonical(obj)+b'\n\n','more_body':True})
  try:
   for index in range(2):
    if stop.is_set():break
    aid=rid+f'/a{index+1}';fault=(c['faults']+[None,None])[index]
    a={'request_id':rid,'attempt_id':aid,'mode':c['mode'],'target':f'logical-{index+1}-same-backend',
      'injected_fault':fault,'started_ns':time.monotonic_ns(),'usage':None,'usage_source':'unknown',
      'generated_content':'','finish':None,'worker_joined':False,'outcome':None,'raw_sse':''}
    r['attempts'].append(a);event('attempt_started',attempt_id=aid)
    q=asyncio.Queue(8)
    async def produce():
     self.worker_count+=1
     try:
      async for item in self.source(c,a,fault):
       if item['kind']=='content':a['generated_content']+=item['text'];event('generated',attempt_id=aid,text=item['text'])
       elif item['kind']=='usage':a.update(usage=item['usage'],usage_source='native_stream_usage' if c['mode']=='gpu' else 'synthetic_fixture')
       elif item['kind']=='finish':a['finish']=item['finish']
       if stop.is_set():event('late_discard',attempt_id=aid,kind=item['kind']);continue
       await q.put(item)
      await q.put({'kind':'end'})
     except asyncio.CancelledError:event('worker_cancelled',attempt_id=aid);raise
     except Exception as e:await q.put({'kind':'error','reason':e.reason if isinstance(e,Fault) else type(e).__name__,'retryable':isinstance(e,Fault) and e.retryable})
     finally:self.worker_count-=1;event('worker_exited',attempt_id=aid)
    worker=asyncio.create_task(produce());failure=None
    try:
     while True:
      getter=asyncio.create_task(q.get());stopper=asyncio.create_task(stop.wait())
      done,_=await asyncio.wait([getter,stopper],timeout=.12 if fault=='pre_timeout' else 15,return_when=asyncio.FIRST_COMPLETED)
      if not done:
       getter.cancel();stopper.cancel();await asyncio.gather(getter,stopper,return_exceptions=True)
       failure={'reason':'first_content_timeout','retryable':True};event('attempt_timeout',attempt_id=aid);break
      if stop.is_set():
       getter.cancel();stopper.cancel();await asyncio.gather(getter,stopper,return_exceptions=True);break
      stopper.cancel();await asyncio.gather(stopper,return_exceptions=True);item=getter.result();kind=item['kind']
      if kind=='content':
       if c.get('review'):
        failure={'reason':'review_rejected' if c['review']=='reject' else 'review_unavailable','retryable':False};break
       if reason is not None:event('late_discard',attempt_id=aid,kind=kind);continue
       text=item['text']
       event('content_send_started',attempt_id=aid)
       await packet({'id':rid,'attempt_id':aid,'generation_id':c['generation_id'],'type':'content','content':text})
       r['committed']=True;r['sent_content']+=text;event('content_sent',attempt_id=aid,text=text,after_stop=False);first.set()
      elif kind=='error':failure=item;break
      elif kind=='end':
       if a['finish'] not in ('stop','length'):failure={'reason':'incomplete_stream','retryable':True}
       break
    finally:
     if not worker.done():worker.cancel()
     await asyncio.gather(worker,return_exceptions=True)
     # A cancellation-resistant fixture can yield a late chunk; it is never forwarded.
     while not q.empty():
      late=q.get_nowait()
      if late['kind']=='content':event('late_discard',attempt_id=aid,kind='content')
     a.update(ended_ns=time.monotonic_ns(),worker_joined=worker.done(),outcome=reason or (failure['reason'] if failure else 'completed'))
     if self.settlements.add(aid,a['usage']):r['settlements'].append({'attempt_id':aid,'usage':a['usage'],'source':a['usage_source']})
     if c.get('duplicate_settlement'):event('settlement_replayed',attempt_id=aid,inserted=self.settlements.add(aid,a['usage']))
     event('attempt_joined',attempt_id=aid)
    if reason is not None:break
    if failure:
     if can_retry(r['committed'],c['idempotency_key'],failure['retryable'],len(r['attempts'])):
      event('retry_allowed',from_attempt=aid);continue
     r['terminal']=failure['reason'] if failure['reason'].startswith('review_') else 'backend_error';break
    r['terminal']='completed';break
   r['terminal']=reason or r['terminal'] or 'backend_error'
   if reason!='client_disconnected':
    await packet({'id':rid,'type':'terminal','terminal':r['terminal'],'generation_id':c['generation_id'],'attempt_ids':[a['attempt_id'] for a in r['attempts']],'settlements':r['settlements'],'finish':r['attempts'][-1]['finish'] if r['terminal']=='completed' else None})
    await send({'type':'http.response.body','body':b'data: [DONE]\n\n','more_body':True})
    await send({'type':'http.response.body','body':b'','more_body':False})
  finally:
   watcher.cancel()
   if controller and not controller.done():controller.cancel()
   await asyncio.gather(watcher,*([controller] if controller else []),return_exceptions=True)
   self.active.pop(rid,None);r.update(terminal=reason or r['terminal'] or 'transport_error',ended_ns=time.monotonic_ns(),sent_sha256=sha(r['sent_content'].encode()))
   event('request_finished',terminal=r['terminal']);self.save(r)

 async def source(self,c,a,fault):
  if fault=='unconnected':
   # Actual refused TCP connection, deliberately chosen closed port.
   try:
    async with httpx.AsyncClient(timeout=.3) as client:await client.get('http://127.0.0.1:1')
   except httpx.ConnectError:raise Fault('connect_refused',True)
   raise Fault('fault_port_unexpectedly_open')
  if c['mode']=='controlled':
   if fault=='pre_timeout':await asyncio.sleep(.5)
   try:
    for i in range(4):
     await asyncio.sleep(.03 if i else .005)
     if i==1 and fault=='post_break':raise Fault('injected_stream_break',True)
     yield {'kind':'content','text':['甲','乙','丙','丁'][i]}
    yield {'kind':'usage','usage':{'prompt_tokens':3,'completion_tokens':4,'total_tokens':7}}
    yield {'kind':'finish','finish':'stop'}
   except asyncio.CancelledError:
    if c.get('late'):
     await asyncio.sleep(.005);yield {'kind':'content','text':'迟到'}
    else:raise
   return
  model_body={'model':'exp26-qwen3-0.6b','messages':[{'role':'user','content':'从1开始连续写整数，用逗号分隔，至少写到100，不要省略。' if c['case_id']!='gpu-normal' else '只输出数字7。'}],
    'max_tokens':192 if c['case_id']!='gpu-normal' else 32,'temperature':0,'seed':26,'stream':True,
    'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False},'ignore_eos':c['case_id'] in ('gpu-disconnect','gpu-drain-timeout')}
  a.update(backend_body=model_body,backend_body_sha256=sha(canonical(model_body)))
  pending=bytearray();done=0;finished=False;content_count=0;decoder=codecs.getincrementaldecoder('utf-8')()
  async with httpx.AsyncClient(timeout=20) as client:
   async with client.stream('POST',self.backend+'/v1/chat/completions',content=canonical(model_body),headers={'Content-Type':'application/json','X-Exp26-Request-ID':a['request_id'],'X-Exp26-Attempt-ID':a['attempt_id']}) as resp:
    a['http_status']=resp.status_code
    if resp.status_code!=200:raise Fault('backend_http_error',True)
    async for chunk in resp.aiter_bytes():
     a['raw_sse']+=decoder.decode(chunk)
     pending.extend(chunk)
     while b'\n\n' in pending:
      packet,_,tail=pending.partition(b'\n\n');pending=bytearray(tail)
      data=b'\n'.join(line[5:].lstrip() for line in packet.splitlines() if line.startswith(b'data:'))
      if not data:continue
      if data==b'[DONE]':done+=1;continue
      if done:raise Fault('event_after_done')
      obj=json.loads(data)
      if obj.get('usage') is not None:yield {'kind':'usage','usage':obj['usage']}
      for choice in obj.get('choices',[]):
       text=choice.get('delta',{}).get('content')
       if text:
        if finished:raise Fault('content_after_finish')
        content_count+=1
        if fault=='pre_timeout' and content_count==1:await asyncio.sleep(.5)
        if fault=='post_break' and content_count==2:raise Fault('injected_stream_break',True)
        yield {'kind':'content','text':text}
        if c.get('client_disconnect') or c.get('control'):await asyncio.sleep(.03)
       if choice.get('finish_reason') is not None:
        if finished:raise Fault('duplicate_finish')
        finished=True;yield {'kind':'finish','finish':choice['finish_reason']}
  if done!=1 or pending.strip() or not finished:raise Fault('incomplete_stream',True)
