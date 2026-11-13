from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""One joint lab path: completed-response review/cache plus fixed exp26 lifecycle."""
import asyncio,json,time,os
from pathlib import Path
from lifecycle import Gateway as Lifecycle,Fault,canonical,sha,valid_usage

async def wait_native_release(path,attempt_id,timeout=5):
 """Lab-only shared CPU audit acknowledgement; never a CUDA-stop claim."""
 deadline=time.monotonic()+timeout;offset=0;pending='';terminal=None
 while time.monotonic()<deadline:
  if path.exists():
   with path.open() as stream:
    stream.seek(offset);pending+=stream.read();offset=stream.tell()
   while '\n' in pending:
    line,pending=pending.split('\n',1)
    if not line:continue
    row=json.loads(line)
    if row.get('attempt_id')!=attempt_id:continue
    ns=row['backend_monotonic_ns']
    if row.get('event')=='engine_finished' or (row.get('event')=='abort_returned' and row.get('error') is None):
     terminal=max(terminal or 0,ns)
    tracker=row.get('tracker')
    if (terminal is not None and ns>=terminal and row.get('event')=='state_after'
        and row.get('snapshot_complete') is True and row.get('error') is None
        and row.get('pending_or_unfinished') is False and row.get('engine_pending_or_unfinished') is False
        and isinstance(tracker,dict) and set(tracker)=={'active_stream','new_pending','abort_pending'}
        and all(v is False for v in tracker.values())):return
  await asyncio.sleep(.005)
 raise RuntimeError('native release acknowledgement timeout: '+attempt_id)

class Admission:
 def __init__(self):self.sem=asyncio.Semaphore(1);self.reserved=0
 async def enter(self):
  if self.reserved>=2:raise OverflowError('full')
  self.reserved+=1
  try:await asyncio.wait_for(self.sem.acquire(),15)
  except BaseException:self.reserved-=1;raise
 def release(self):self.reserved-=1;self.sem.release()

class Gateway:
 def __init__(self,plan,encoder,log_path=None,identity=None,native_source=None):
  self.plan=plan;self.cases={c['case_id']:dict(c) for c in plan['cases']};self.encoder=encoder
  self.log_path=Path(log_path) if log_path else None;self.records=[];self.cache={};self.policy='rule-v1'
  self.identity=identity or {'model_sha256':'fixture','template_sha256':'fixture'};self.meta={};self.admission=Admission()
  self.base=Lifecycle(list(self.cases.values()),backend=f'http://127.0.0.1:{plan["backend_port"]}')
  self.native_source=native_source or self.base.source;self.base.source=self.source;self.base.save=self.save
  self.clock_domain=self.base.clock_domain
  if native_source is None:
   async def before_retry(c,a):
    # HTTP close only initiates native cancellation. Await tracker/scheduler acknowledgement.
    await wait_native_release(Path(os.environ['EXP27_AUDIT_PATH']),a['attempt_id'])
   self.base.before_retry=before_retry
 def save(self,r):
  r.update(self.meta.pop(r['case_id']))
  if r['terminal']=='completed' and r['route']=='integrated' and r['cache']=='miss':
   a=r['attempts'][-1]
   if a['finish']=='stop' and valid_usage(a['usage']) and r['sent_content'] and 'LAB_BLOCK' not in r['sent_content']:
    origin={'request_id':r['request_id'],'attempt_id':a['attempt_id'],'usage':a['usage'],'content_sha256':sha(r['sent_content'].encode()),'key':r['cache_key']}
    self.cache[r['cache_key']]={'text':r['sent_content'],'origin':origin,'tenant':r['tenant_id'],'policy':r['policy']}
  self.records.append(r)
  if self.log_path:
   with self.log_path.open('a') as f:f.write(json.dumps(r,ensure_ascii=False)+'\n')
 async def source(self,c,a,fault):
  if c.get('hold_seconds'):await asyncio.sleep(c['hold_seconds'])
  if c['route']=='direct':
   async for item in self.native_source(c,a,fault):yield item
   return
  text=[]
  async for item in self.native_source(c,a,fault):
   if item['kind']=='content':text.append(item['text'])
   else:yield item
  a['backend_generated_content']=''.join(text)
  if 'LAB_BLOCK' in a['backend_generated_content']:raise Fault('review_rejected')
  for offset in range(0,len(a['backend_generated_content']),4):
   if offset and c.get('delivery_break'):raise Fault('injected_delivery_break')
   yield {'kind':'content','text':a['backend_generated_content'][offset:offset+4]}
   await asyncio.sleep(0)
 async def __call__(self,scope,receive,send):
  if scope['type']!='http':return
  async def reply(status,obj):
   headers=[(b'content-type',b'application/json')]
   if obj.get('request_id'):headers.append((b'x-request-id',obj['request_id'].encode()))
   await send({'type':'http.response.start','status':status,'headers':headers});await send({'type':'http.response.body','body':canonical(obj)})
  if scope['path']=='/health':return await reply(200,{'active':len(self.base.active),'workers':self.base.worker_count,'reserved':self.admission.reserved,'draining':self.base.draining})
  body=bytearray()
  while True:
   m=await receive()
   if m['type']=='http.disconnect':return
   body.extend(m.get('body',b''))
   if not m.get('more_body'):break
  if scope['path'].startswith('/lab/'):
   if scope['path']=='/lab/cache-clear':self.cache.clear()
   elif scope['path']=='/lab/policy':self.policy=json.loads(body)['policy']
   elif scope['path']=='/lab/drain':await self.base.drain(json.loads(body)['deadline'])
   elif scope['path']=='/lab/reset':
    if self.base.active or self.base.worker_count or self.admission.reserved:return await reply(409,{'error':'not idle'})
    self.base.draining=False
   else:return await reply(404,{'error':'unknown admin operation'})
   return await reply(200,{'ok':True})
  try:
   incoming=json.loads(body);c=self.cases[incoming.pop('case_id')]
  except (KeyError,ValueError,AttributeError):return await reply(400,{'error':'unknown frozen case'})
  rid=c['request_id'];ingress=time.monotonic_ns();headers=dict(scope.get('headers',[]));tenant={b'Bearer lab-a':'tenant-a',b'Bearer lab-b':'tenant-b'}.get(headers.get(b'authorization'))
  if rid in self.base.seen:return await reply(409,{'error':'duplicate request','request_id':rid})
  meta={'input_body':incoming,'input_sha256':sha(canonical(incoming)),'tenant_id':tenant,'route':c['route'],'stratum':c['stratum'],
        'identity':self.identity,'policy':self.policy,'ingress_ns':ingress,'cache':'not_checked','cache_key':None,'cache_origin':None,'prompt_tokens':None,'admission_wait_ns':0}
  self.meta[c['case_id']]=meta
  async def reject(terminal,status):
   self.base.seen.add(rid)
   r={'case_id':c['case_id'],'request_id':rid,'generation_id':'g0','mode':'gpu','clock_domain':self.clock_domain,'started_ns':ingress,'ended_ns':time.monotonic_ns(),'events':[],'attempts':[],'settlements':[],'sent_content':'','sent_sha256':sha(b''),'committed':False,'terminal':terminal,'idempotency_key':c['idempotency_key']}
   self.save(r);return await reply(status,{'error':terminal,'request_id':rid})
  if self.base.draining:return await reject('draining',503)
  if scope['path']!='/'+c['route']:return await reject('capability_rejected',400)
  if c['route']=='integrated' and tenant is None:return await reject('authentication_rejected',401)
  allowed={'model','messages','max_tokens','stream','temperature','seed'}
  if (set(incoming)!=allowed or incoming.get('model')!='lab-qwen' or incoming.get('stream') is not True
      or type(incoming.get('max_tokens')) is not int or not 1<=incoming['max_tokens']<=192
      or type(incoming.get('seed')) is not int or incoming['seed']!=27 or incoming.get('temperature')!=0
      or not isinstance(incoming.get('messages'),list) or not incoming['messages']
      or any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('user','system','assistant') or not isinstance(m['content'],str) for m in incoming['messages'])):
   return await reject('capability_rejected',400)
  tokens=self.encoder(incoming['messages']);meta['prompt_tokens']=len(tokens);meta['prompt_ids_sha256']=sha(canonical(tokens))
  if len(tokens)>512:return await reject('budget_rejected',400)
  native={**incoming,'model':alias(27),'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
  c['backend_body']=native
  key=sha(canonical({'tenant':tenant,'body':native,'prompt_ids_sha256':meta['prompt_ids_sha256'],'identity':self.identity,'policy':self.policy}))
  meta['cache_key']=key
  meta['cache']='bypass' if c['route']=='direct' else 'miss'
  if c['route']=='integrated' and key in self.cache:
   entry=self.cache[key];meta.update(cache='hit',cache_origin=entry['origin']);self.base.seen.add(rid)
   r={'case_id':c['case_id'],'request_id':rid,'generation_id':'g0','mode':'gpu','clock_domain':self.clock_domain,'started_ns':ingress,'events':[],'attempts':[],'settlements':[],'sent_content':'','committed':False,'terminal':None,'idempotency_key':c['idempotency_key']}
   def event(name,**kw):r['events'].append({'event':name,'ns':time.monotonic_ns(),**kw})
   await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'text/event-stream'),(b'x-request-id',rid.encode())]})
   try:
    event('content_send_started',attempt_id=None)
    await send({'type':'http.response.body','body':b'data: '+canonical({'type':'content','id':rid,'generation_id':'g0','attempt_id':None,'content':entry['text']})+b'\n\n','more_body':True})
    r.update(sent_content=entry['text'],committed=True);event('content_sent',attempt_id=None,text=entry['text'])
    await send({'type':'http.response.body','body':b'data: '+canonical({'type':'terminal','id':rid,'generation_id':'g0','terminal':'completed','finish':'stop','attempt_ids':[],'settlements':[],'cache':'hit','cache_origin':entry['origin']})+b'\n\ndata: [DONE]\n\n','more_body':False});r['terminal']='completed'
   finally:
    r.update(terminal=r['terminal'] or 'client_disconnected',ended_ns=time.monotonic_ns(),sent_sha256=sha(r['sent_content'].encode()));self.save(r)
   return
  acquired=False
  if c['route']=='integrated':
   start=time.monotonic_ns()
   try:await self.admission.enter();acquired=True
   except (OverflowError,asyncio.TimeoutError):return await reject('admission_rejected',429)
   meta['admission_wait_ns']=time.monotonic_ns()-start
  # Feed only the validated frozen ID into the archived lifecycle, while source uses actual native input.
  first=True
  async def replay():
   nonlocal first
   if first:first=False;return {'type':'http.request','body':canonical({'case_id':c['case_id']}),'more_body':False}
   return await receive()
  async def traced_send(message):
   raw=message.get('body',b'')
   if raw.startswith(b'data: {'):
    obj=json.loads(raw[6:].strip())
    if obj.get('type')=='terminal':
     obj.update(cache=meta['cache'],cache_origin=None);message={**message,'body':b'data: '+canonical(obj)+b'\n\n'}
   await send(message)
  try:await self.base(scope,replay,traced_send)
  finally:
   if acquired:self.admission.release()
