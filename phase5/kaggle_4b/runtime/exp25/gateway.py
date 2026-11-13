from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""One lab gateway: exact reviewed-response cache, bounded admission, one attempt ledger."""
import asyncio,hashlib,json,time,uuid,os
from dataclasses import dataclass,field
from pathlib import Path
from collections import OrderedDict
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,StreamingResponse
import httpx


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
ZERO={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}

@dataclass
class Config:
 log_path:Path
 active_limit:int=1
 queue_limit:int=1
 queue_timeout:float=20
 prompt_limit:int=512
 cache_entries:int=64
 cache_ttl:float=300
 identity:dict=field(default_factory=lambda:{'model_fingerprint':'fixture-model','tokenizer_fingerprint':'fixture-tokenizer','template_sha256':'fixture-template'})

@dataclass
class BackendResult:
 content:str
 finish:str|None
 usage:dict|None
 raw_sse:str
 status:int

class Overloaded(Exception):pass
class ProtocolError(Exception):pass

class Admission:
 def __init__(self,active,waiting,timeout):
  self.sem=asyncio.Semaphore(active);self.capacity=active+waiting;self.reserved=0;self.timeout=timeout
 async def enter(self):
  if self.reserved>=self.capacity:raise Overloaded('queue_full')
  self.reserved+=1
  try:await asyncio.wait_for(self.sem.acquire(),self.timeout)
  except BaseException:
   self.reserved-=1;raise
 def release(self):self.sem.release();self.reserved-=1


def measured_usage(value):
 if not isinstance(value,dict):return None
 fields=['prompt_tokens','completion_tokens','total_tokens']
 if any(type(value.get(x)) is not int or value[x]<0 for x in fields):return None
 if value['prompt_tokens']+value['completion_tokens']!=value['total_tokens']:return None
 return {x:value[x] for x in fields}

class HTTPBackend:
 def __init__(self,url,model=alias(25)):
  self.url=url;self.model=model
 async def generate(self,body,request_id,attempt_id,emit):
  raw=bytearray();pending=bytearray();content=[];finish=None;usage=None;done=0
  async with httpx.AsyncClient(timeout=httpx.Timeout(45,connect=5)) as client:
   async with client.stream('POST',self.url+'/v1/chat/completions',content=canonical(body),
       headers={'Content-Type':'application/json','X-Exp25-Request-Id':request_id,'X-Exp25-Attempt-Id':attempt_id}) as response:
    emit('backend_headers',http_status=response.status_code)
    async for chunk in response.aiter_bytes():
     raw.extend(chunk);pending.extend(chunk)
     while b'\n\n' in pending:
      event,_,tail=pending.partition(b'\n\n');pending=bytearray(tail)
      payload=b'\n'.join(x[5:].lstrip(b' ') for x in event.splitlines() if x.startswith(b'data:'))
      if not payload:continue
      if payload==b'[DONE]':done+=1;continue
      if done:raise ProtocolError('event after DONE')
      obj=json.loads(payload)
      if obj.get('usage') is not None:usage=obj['usage']
      for choice in obj.get('choices',[]):
       text=choice.get('delta',{}).get('content')
       if text:
        if finish is not None:raise ProtocolError('content after backend finish')
        if not content:emit('backend_first_content')
        content.append(text)
       if choice.get('finish_reason') is not None:
        if finish is not None:raise ProtocolError('duplicate/conflicting backend finish')
        finish=choice['finish_reason']
    if response.status_code!=200:return BackendResult('',None,None,raw.decode(errors='replace'),response.status_code)
  if done!=1 or pending.strip() or finish is None:raise ProtocolError('incomplete backend SSE')
  return BackendResult(''.join(content),finish,usage,raw.decode(),200)

class Gateway:
 def __init__(self,cfg,backend,encoder):
  self.cfg=cfg;self.backend=backend;self.encoder=encoder;self.identity=dict(cfg.identity)
  self.policy_version='rule-v1';self.route_version='single-v1'
  self.cache=OrderedDict();self.admission=Admission(cfg.active_limit,cfg.queue_limit,cfg.queue_timeout)
  self.clock_domain=f'kaggle-gateway-{os.getpid()}'
 def append(self,record):
  self.cfg.log_path.parent.mkdir(parents=True,exist_ok=True)
  with self.cfg.log_path.open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
 async def handle(self,request):
  rid='req-'+uuid.uuid4().hex;t=time.monotonic_ns()
  r={'request_id':rid,'tenant_id':None,'component':'gateway','clock_domain':self.clock_domain,
     'case_id':request.headers.get('x-lab-case-id'),'started_ns':t,'events':[],'attempts':[],'cache':'not_checked','generation_usage':dict(ZERO),
     'usage_source':'no_generation_attempt','cache_origin_usage':None,'gateway_emitted_utf8_bytes':0,
     'gateway_emitted_sha256':sha(b''),'terminal':None,'policy_version':self.policy_version,
     'route_version':self.route_version,'identity':dict(self.identity)}
  def emit(event,**fields):r['events'].append({'event':event,'monotonic_ns':time.monotonic_ns(),**fields})
  emit('received')
  def finish(terminal,status):
   if r['terminal'] is not None:raise RuntimeError('duplicate terminal')
   r.update(terminal=terminal,http_status=status)
   emit('terminal',terminal=terminal);r['ended_ns']=time.monotonic_ns();self.append(r)
  def reject(terminal,status):
   finish(terminal,status)
   return JSONResponse({'error':{'type':terminal},'request_id':rid},status_code=status,headers={'X-Request-Id':rid})
  auth=request.headers.get('authorization','')
  tenant={'Bearer lab-a':'tenant-a','Bearer lab-b':'tenant-b'}.get(auth)
  if tenant is None:return reject('authentication_rejected',401)
  r['tenant_id']=tenant;emit('identity_accepted')
  try:body=await request.json()
  except Exception:return reject('capability_rejected',400)
  r['client_body_sha256']=sha(canonical(body))
  allowed={'model','messages','stream','max_tokens','temperature','seed'}
  if (not isinstance(body,dict) or set(body)-allowed or body.get('model') not in ('lab-qwen','lab-qwen-route2')
      or body.get('stream') is not True or type(body.get('max_tokens')) is not int
      or not 1<=body['max_tokens']<=96 or type(body.get('temperature',0)) not in (float,int)
      or body.get('temperature',0)!=0 or type(body.get('seed',25)) is not int or body.get('seed',25)!=25):
   return reject('capability_rejected',400)
  messages=body.get('messages')
  if (not isinstance(messages,list) or not messages or len(messages)>12
      or any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('system','user','assistant')
             or not isinstance(m['content'],str) or not m['content'] for m in messages)):
   return reject('capability_rejected',400)
  emit('capability_accepted')
  try:tokens=self.encoder(messages)
  except Exception:return reject('encoding_rejected',400)
  if len(tokens)>self.cfg.prompt_limit:return reject('budget_rejected',400)
  r.update(prompt_tokens_computed=len(tokens),prompt_ids_sha256=sha(canonical(tokens)))
  emit('budget_accepted')
  route='single-v2' if body['model']=='lab-qwen-route2' else self.route_version
  r['route_version']=route
  backend_body={'model':getattr(self.backend,'model',alias(25)),'messages':messages,
    'max_tokens':body['max_tokens'],'temperature':0,'seed':25,'stream':True,
    'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
  key=sha(canonical({'tenant':tenant,'body':backend_body,'tokens_sha256':r['prompt_ids_sha256'],
       'identity':self.identity,'policy':self.policy_version,'route':route}))
  r['cache_key']=key;now=time.monotonic();cached=self.cache.get(key)
  if cached and now-cached['stored_at']<=self.cfg.cache_ttl:
   self.cache.move_to_end(key);r['cache']='hit';r['cache_origin_usage']=cached['usage']
   r['cache_origin_request_id']=cached['request_id'];r['cache_origin_attempt_id']=cached['attempt_id']
   r['cache_origin_policy_version']=cached['policy'];emit('cache_hit')
   result=BackendResult(cached['content'],'stop',None,'',200)
  else:
   self.cache.pop(key,None);r['cache']='miss';emit('cache_miss')
   q=time.monotonic_ns();emit('admission_requested')
   try:await self.admission.enter()
   except (Overloaded,asyncio.TimeoutError):return reject('admission_rejected',429)
   r['admission_wait_ms']=(time.monotonic_ns()-q)/1e6;emit('admission_entered')
   aid='att-'+uuid.uuid4().hex
   attempt={'attempt_id':aid,'request_id':rid,'tenant_id':tenant,'backend_id':'kaggle-qwen-single',
    'route_version':route,'backend_body_sha256':sha(canonical(backend_body)),'backend_body':backend_body,
    'started_ns':time.monotonic_ns(),'http_status':None,'usage_raw':None,'usage':None,'usage_source':'unknown'}
   r['attempts'].append(attempt);emit('route_selected',backend_id=attempt['backend_id'])
   def backend_emit(event,**fields):
    if event=='backend_headers':attempt['http_status']=fields['http_status']
    emit(event,attempt_id=aid,**fields)
   failed=False
   try:
    result=await self.backend.generate(backend_body,rid,aid,backend_emit)
    attempt.update(http_status=result.status,usage_raw=result.usage,usage=measured_usage(result.usage),
      response_sse_sha256=sha(result.raw_sse.encode()),finish_reason=result.finish,
      generated_utf8_bytes=len(result.content.encode()),generated_sha256=sha(result.content.encode()))
    attempt['usage_source']='backend_stream_usage' if attempt['usage'] is not None else 'unknown'
    r['generation_usage']=attempt['usage'];r['usage_source']=attempt['usage_source']
   except Exception as e:
    attempt['error_type']=type(e).__name__;r['generation_usage']=None;r['usage_source']='unknown'
    failed=True
   finally:
    attempt['ended_ns']=time.monotonic_ns();self.admission.release()
   if failed:return reject('backend_error',502)
   if result.status!=200:return reject('backend_error',502)
   emit('backend_completed',finish_reason=result.finish)
   if result.finish not in ('stop','length') or not result.content:return reject('backend_incomplete',502)
   if 'LAB_BLOCK' in result.content:
    emit('review_rejected');return reject('review_rejected',422)
   emit('review_allowed')
   if result.finish=='stop' and measured_usage(result.usage) is not None:
    self.cache[key]={'content':result.content,'usage':result.usage,'request_id':rid,'attempt_id':aid,
                    'policy':self.policy_version,'stored_at':time.monotonic()}
    while len(self.cache)>self.cfg.cache_entries:self.cache.popitem(last=False)
    emit('cache_stored')
  text=result.content
  async def stream():
   completed=False
   try:
    # Entire backend output has already passed the full-response lab rule gate.
    for offset in range(0,len(text),12):
     chunk=text[offset:offset+12]
     if offset==0:emit('client_first_content')
     r['gateway_emitted_utf8_bytes']+=len(chunk.encode())
     payload={'id':rid,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{'content':chunk},'finish_reason':None}]}
     yield 'data: '+json.dumps(payload,ensure_ascii=False)+'\n\n'
    yield 'data: '+json.dumps({'id':rid,'choices':[{'index':0,'delta':{},'finish_reason':result.finish}]})+'\n\n'
    # Gateway extension clearly separates this request's generation from origin usage.
    yield 'data: '+json.dumps({'id':rid,'choices':[],'gateway_usage':r['generation_usage'],'cache':r['cache']})+'\n\n'
    yield 'data: [DONE]\n\n';completed=True
   finally:
    r['gateway_emitted_sha256']=sha(text.encode()) if completed else None
    finish('delivered' if completed else 'client_disconnected',200)
  return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Request-Id':rid,'X-Lab-Cache':r['cache']})


def create_app(config,backend,encoder):
 app=FastAPI();gw=Gateway(config,backend,encoder);app.state.gateway=gw
 @app.get('/health')
 async def health():return {'ok':True,'active_and_waiting':gw.admission.reserved,'capabilities':'text chat stream; full-response rule gate; exact response cache; one attempt'}
 @app.post('/v1/chat/completions')
 async def chat(request:Request):return await gw.handle(request)
 return app
