from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""Create a new frozen run, execute archived runner; keep failed planned requests."""
import argparse,json,pathlib,hashlib,sys,subprocess,time,asyncio,socket,os,signal,platform,codecs

D=pathlib.Path(__file__).resolve().parent
R=pathlib.Path(os.environ.get('P5_EXP_ROOT','/kaggle/working/p5-exp25'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def live(port):
 with socket.socket() as s:s.settimeout(.2);return s.connect_ex(('127.0.0.1',port))==0

def make_plan():
 p={'schema':1,'experiment':'exp25','backend_model':alias(25),'active_limit':1,'queue_limit':1,
    'gateway_port':8125,'backend_port':8025,'cases':[],'steps':[],'burst_groups':[],
    'scope':'one real small GPU, synthetic tenants, full-response lab rule gate and exact response cache; semantic diagnostic separate'}
 def add(name,token='lab-a',body=None,status=200,terminals=None,cache=None,**kw):
  c={'case_id':name,'token':token,'body':body or {'model':'lab-qwen','messages':[{'role':'user','content':'只输出数字7。'}],'stream':True,'max_tokens':32},
     'status':status,'terminals':terminals or ['delivered'],**kw}
  if cache:c['cache']=cache
  p['cases'].append(c);return c
 def seq(name,**kw):c=add(name,**kw);p['steps'].append({'case_ids':[c['case_id']]});return c
 base={'model':'lab-qwen','messages':[{'role':'user','content':'只输出数字7。'}],'stream':True,'max_tokens':32}
 seq('a-first',cache='miss',expected_text='7');seq('a-repeat',cache='hit',expected_text='7')
 seq('b-first',token='lab-b',cache='miss',expected_text='7');seq('b-repeat',token='lab-b',cache='hit',expected_text='7')
 seq('spoofed-tenant-header',headers={'X-Tenant-Id':'tenant-b'},cache='hit',expected_text='7')
 for name in ['route2-first','route2-repeat']:seq(name,body={**base,'model':'lab-qwen-route2'},cache='miss' if name.endswith('first') else 'hit',expected_text='7')
 for name in ['options-first','options-repeat']:seq(name,body={**base,'max_tokens':16},cache='miss' if name.endswith('first') else 'hit',expected_text='7')
 seq('unauthenticated',token='invalid',status=401,terminals=['authentication_rejected'])
 for name,patch in [('tools',{'tools':[]}),('format',{'response_format':{'type':'json_object'}}),('nonstream',{'stream':False}),('wrong-seed',{'seed':999}),('zero-output-budget',{'max_tokens':0}),('unknown-model',{'model':'unknown'}),('image-content',{'messages':[{'role':'user','content':[{'type':'text','text':'hello'}]}]}),('tenant-body',{'tenant_id':'tenant-b'})]:
  seq('reject-'+name,body={**base,**patch},status=400,terminals=['capability_rejected'])
 seq('over-prompt-budget',body={**base,'messages':[{'role':'user','content':'hello '*800}]},status=400,terminals=['budget_rejected'])
 seq('invalid-json',raw_body='{broken',status=400,terminals=['capability_rejected'])
 for i in range(2):seq(f'review-{i}',body={**base,'messages':[{'role':'user','content':'请只输出字符串LAB_BLOCK，不要添加其他内容。'}]},status=422,terminals=['review_rejected'],cache='miss')
 for i in range(2):seq(f'length-{i}',body={**base,'messages':[{'role':'user','content':'请从1开始连续写整数，用逗号分隔，至少写到100，不要省略。'}],'max_tokens':2},cache='miss',finish='length')
 for group in range(2):
  names=[]
  for i in range(8):
   name=f'burst-{group}-{i}';names.append(name)
   add(name,token='lab-a' if i%2==0 else 'lab-b',body={**base,'messages':[{'role':'user','content':f'任务编号{group}-{i}：请从1开始连续写整数，用逗号分隔，至少写到100，不要省略。'}],'max_tokens':64},status=None,terminals=['delivered','admission_rejected'])
  hit=f'burst-{group}-warm-hit';add(hit,cache='hit',expected_text='7');names.append(hit)
  p['steps'].append({'case_ids':names});p['burst_groups'].append({'case_ids':names[:-1]})
 return p

async def execute(out):
 import httpx
 p=json.loads((out/'plan.json').read_text())
 for name,digest in p['code_sha256'].items():assert sha(out/'code'/name)==digest
 assert live(p['backend_port']) and not live(p['gateway_port']),'backend/gateway precondition'
 proc=None
 log=(out/'gateway-server.log').open('w')
 async def call(c,client):
  data=c['raw_body'].encode() if 'raw_body'in c else canonical(c['body'])
  row={'case_id':c['case_id'],'clock_domain':f'kaggle-client-{os.getpid()}','request_sha256':hashlib.sha256(data).hexdigest(),
       'started_ns':time.monotonic_ns(),'first_content_ns':None,'request_id':None,'status':None,'raw':''}
  chunks=[];pending='';decoder=codecs.getincrementaldecoder('utf-8')()
  try:
   async with client.stream('POST',f'http://127.0.0.1:{p["gateway_port"]}/v1/chat/completions',content=data,
      headers={'Content-Type':'application/json','Authorization':'Bearer '+c['token'],'X-Lab-Case-Id':c['case_id'],**c.get('headers',{})}) as resp:
    row.update(status=resp.status_code,request_id=resp.headers.get('x-request-id'))
    async for chunk in resp.aiter_bytes():
     chunks.append(chunk)
     # Count receipt of parsed content events; chunk bytes are retained independently.
     pending+=decoder.decode(chunk)
     while '\n\n' in pending:
      event,pending=pending.split('\n\n',1)
      if event.startswith('data: {'):
       obj=json.loads(event[6:])
       if any(x.get('delta',{}).get('content') for x in obj.get('choices',[])) and row['first_content_ns'] is None:row['first_content_ns']=time.monotonic_ns()
  except Exception as e:row['error_type']=type(e).__name__;row['error']=str(e)
  row.update(raw=b''.join(chunks).decode(errors='replace'),ended_ns=time.monotonic_ns())
  return row
 try:
  proc=subprocess.Popen([sys.executable,'-B',str(out/'code/serve_gateway.py'),'--out',str(out),'--port',str(p['gateway_port'])],stdout=log,stderr=log,start_new_session=True)
  deadline=time.monotonic()+30
  async with httpx.AsyncClient(timeout=45,limits=httpx.Limits(max_connections=20)) as client:
   while time.monotonic()<deadline:
    if proc.poll() is not None:raise RuntimeError('gateway startup failed')
    try:
     r=await client.get(f'http://127.0.0.1:{p["gateway_port"]}/health')
     if r.status_code==200:break
    except httpx.HTTPError:pass
    await asyncio.sleep(.1)
   else:raise RuntimeError('gateway readiness timeout')
   byid={c['case_id']:c for c in p['cases']};records=[]
   for step in p['steps']:
    records.extend(await asyncio.gather(*(call(byid[k],client) for k in step['case_ids'])))
    (out/'clients.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
   health=await client.get(f'http://127.0.0.1:{p["gateway_port"]}/health')
   (out/'gateway-health-end.json').write_text(json.dumps(health.json(),indent=2)+'\n')
  # Wait only for audit append completion, not arbitrary new traffic.
  gwrows=[json.loads(x) for x in (out/'gateway.jsonl').read_text().splitlines()]
  aids={a['attempt_id'] for r in gwrows for a in r['attempts']}
  for _ in range(30):
   allrows=[json.loads(x) for x in (R/'backend.jsonl').read_text().splitlines()]
   chosen=[r for r in allrows if r['attempt_id'] in aids]
   if len(chosen)==len(aids):break
   await asyncio.sleep(.1)
  (out/'backend.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in chosen))
  (out/'backend-snapshot.json').write_text(json.dumps({'full_log_sha256':sha(R/'backend.jsonl'),'selected_attempts':len(chosen),'full_log_rows':len(allrows),'selection':'exact attempt IDs from this gateway run','model_identity_sha256':sha(R/'model-identity.json'),'backend_middleware_sha256':sha(R/'backend_audit.py')},indent=2)+'\n')
  subprocess.run([sys.executable,'-B',str(out/'code/analyze.py'),'--out',str(out)],check=True)
 finally:
  if proc and proc.poll() is None:
   proc.terminate()
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
  log.close()
  (out/'gateway-cleanup.json').write_text(json.dumps({'pid':proc.pid if proc else None,'exited':proc.poll() is not None if proc else None,'port_listening':live(p['gateway_port']),'scope':'this gateway only; backend retained until final cleanup'},indent=2)+'\n')

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--execute',action='store_true');ap.add_argument('--backend-pid',type=int);a=ap.parse_args();out=pathlib.Path(a.out).resolve()
 install_signals()
 if a.execute:asyncio.run(execute(out))
 else:
  out.mkdir(parents=True,exist_ok=False);(out/'code').mkdir()
  for name in ('run.py','gateway.py','serve_gateway.py','analyze.py','backend_audit.py','common.py'):(out/'code'/name).write_bytes((D/name).read_bytes())
  plan=make_plan();plan['code_sha256']={f.name:sha(f) for f in (out/'code').glob('*.py')}
  plan['model_identity']=json.loads((R/'model-identity.json').read_text());plan['backend_started_pid']=a.backend_pid
  (out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
  (out/'freeze.json').write_text(json.dumps({'plan_sha256':sha(out/'plan.json'),'source_sha256':plan['code_sha256']})+'\n')
  exec_frozen([sys.executable,'-B',str(out/'code/run.py'),'--out',str(out),'--execute'])
