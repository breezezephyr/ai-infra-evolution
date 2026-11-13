from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""Single supervisor clock, frozen execution, complete raw evidence, owned process cleanup."""
import argparse,asyncio,codecs,hashlib,json,os,pathlib,resource,shutil,socket,subprocess,sys,time,signal,platform
D=pathlib.Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x] if p.exists() else []
def live(port):
 with socket.socket() as s:s.settimeout(.2);return s.connect_ex(('127.0.0.1',port))==0

def model_identity():
 return portable_identity()

def gpu():
 binary=os.environ.get('EXP27_NVIDIA_SMI') or shutil.which('nvidia-smi')
 if not binary:return None
 try:return subprocess.check_output([binary,'--query-gpu=name,memory.total,memory.used,utilization.gpu','--format=csv,noheader'],text=True).strip()
 except (OSError,subprocess.CalledProcessError):return None

async def execute(out):
 import httpx
 plan=json.loads((out/'plan.json').read_text());root=out.parent
 for n,h in plan['source_sha256'].items():assert sha(out/'code'/n)==h
 assert not any(live(p) for p in [8027,8127])
 domain=f'supervisor-{os.getpid()}';res={'clock_domain':domain,'intervals':[],'cpu':{},'kernel_seconds':None,'paid_currency':None,'exact_weight_residency':None,'scope':'owned service process interval and ready-to-stop interval; not exact weight/kernel residency; CPU wait4 process-family accounting includes only reaped descendants'}
 procs={};logs={};clients=[];health=[];errors=[];before=model_identity();dump(out/'model-identity.json',before)
 def start(name,cmd,env):
  logs[name]=(out/(name+'-server.log')).open('w');t=time.monotonic_ns()
  proc=subprocess.Popen(cmd,cwd=out/'code',env=env,stdout=logs[name],stderr=logs[name],start_new_session=True)
  procs[name]={'proc':proc,'started_ns':t,'ready_ns':None};dump(out/(name+'-startup.json'),{'pid':proc.pid,'command':cmd,'clock_domain':domain,'started_ns':t,'source_sha256':plan['source_sha256']})
 async def wait_native(rid):
  for _ in range(500):
   if any(r.get('request_id')==rid and r.get('event')=='engine_output' for r in rows(out/'backend.jsonl')):return
   await asyncio.sleep(.01)
  raise RuntimeError('no native output before controlled cancel: '+rid)
 async def call(c,client):
  row={'case_id':c['case_id'],'request_id':None,'status':None,'raw':'','started_ns':time.monotonic_ns(),'first_content_ns':None,'clock_domain':f'client-{os.getpid()}','closed_intentionally':False};raw=[];pending='';decoder=codecs.getincrementaldecoder('utf-8')()
  try:
   async with client.stream('POST',f'http://127.0.0.1:8127/{c["route"]}',json={'case_id':c['case_id'],**c['body']},headers={'Authorization':'Bearer '+c['token']}) as resp:
    row.update(status=resp.status_code,request_id=resp.headers.get('x-request-id'))
    if c.get('client_cancel'):
     await wait_native(c['request_id']);await asyncio.sleep(.02);row['closed_intentionally']=True
    else:
     async for chunk in resp.aiter_bytes():
      part=decoder.decode(chunk);raw.append(part);pending+=part
      while '\n\n' in pending:
       frame,pending=pending.split('\n\n',1)
       if frame.startswith('data: {'):
        obj=json.loads(frame[6:])
        if obj.get('type')=='content' and obj.get('content') and row['first_content_ns'] is None:row['first_content_ns']=time.monotonic_ns()
  except Exception as e:row.update(error_type=type(e).__name__,error=str(e))
  row.update(raw=''.join(raw),ended_ns=time.monotonic_ns());clients.append(row);dump(out/'clients.json',clients);return row
 try:
  env=backend_env(27,out/'code',out)
  backend_cmd=plan['backend_command']
  dump(out/'gpu-before.json',{'gpu':gpu()});start('backend',backend_cmd,env)
  async with httpx.AsyncClient(timeout=60,limits=httpx.Limits(max_connections=20)) as client:
   async def ready(name,port):
    for _ in range(1500):
     # Do not poll/reap children: wait4 below records their own resource usage.
     try:
      if (await client.get(f'http://127.0.0.1:{port}/health',timeout=1)).status_code==200:
       procs[name]['ready_ns']=time.monotonic_ns();return
     except httpx.HTTPError:pass
     await asyncio.sleep(.1)
    raise RuntimeError(name+' readiness timeout')
   await ready('backend',8027)
   start('gateway',[sys.executable,'-B',str(out/'code/serve_gateway.py'),'--out',str(out)],env);await ready('gateway',8127)
   byid={c['case_id']:c for c in plan['cases']};base='http://127.0.0.1:8127'
   for step in plan['steps']:
    if step.get('clear_cache'):assert (await client.post(base+'/lab/cache-clear',json={})).status_code==200
    if step.get('policy'):assert (await client.post(base+'/lab/policy',json={'policy':step['policy']})).status_code==200
    if step.get('drain'):
     running=asyncio.create_task(call(byid[step['cases'][0]],client));await wait_native(byid[step['cases'][0]]['request_id'])
     draining=asyncio.create_task(client.post(base+'/lab/drain',json={'deadline':.02}))
     for _ in range(100):
      if (await client.get(base+'/health')).json()['draining']:break
      await asyncio.sleep(.001)
     await call(byid[step['cases'][1]],client);assert (await draining).status_code==200;await running
    else:await asyncio.gather(*(call(byid[k],client) for k in step['cases']))
    for _ in range(500):
     h=(await client.get(base+'/health')).json()
     if h['active']==h['workers']==h['reserved']==0:break
     await asyncio.sleep(.01)
    health.append({'case_ids':step['cases'],'state':h,'ns':time.monotonic_ns()});dump(out/'health.json',health)
    if h['active'] or h['workers'] or h['reserved']:raise RuntimeError('workers did not join')
    if step.get('drain'):assert (await client.post(base+'/lab/reset',json={})).status_code==200
   await asyncio.sleep(.5)
 except BaseException as e:errors.append(type(e).__name__+': '+str(e));dump(out/'run-errors.json',errors)
 finally:
  for name in ['gateway','backend']:
   if name not in procs:continue
   entry=procs[name];proc=entry['proc'];stop_ns=time.monotonic_ns()
   try:os.killpg(proc.pid,signal.SIGTERM)
   except ProcessLookupError:pass
   # wait4 owns reaping, including summed reaped descendant CPU accounting.
   async def reap():return await asyncio.to_thread(os.wait4,proc.pid,0)
   task=asyncio.create_task(reap())
   try:pid,status,usage=await asyncio.wait_for(asyncio.shield(task),20)
   except asyncio.TimeoutError:os.killpg(proc.pid,signal.SIGKILL);pid,status,usage=await task
   ended=time.monotonic_ns();proc.returncode=os.waitstatus_to_exitcode(status)
   res['intervals'].append({'component':name,'pid':pid,'started_ns':entry['started_ns'],'ready_ns':entry['ready_ns'],'stop_requested_ns':stop_ns,'exited_ns':ended,'returncode':proc.returncode})
   res['cpu'][name]={'user_seconds':usage.ru_utime,'system_seconds':usage.ru_stime,'maxrss_kib':usage.ru_maxrss};logs[name].close()
  dump(out/'resources.json',res)
  try:after=model_identity()
  except Exception as exc:after={'files':{}};errors.append('cleanup identity: '+str(exc))
  cleanup={'owned_pids':[r['pid'] for r in res['intervals']],'all_reaped':len(res['intervals'])==len(procs),'ports':{str(p):live(p) for p in [8027,8127]},'gpu':gpu(),'model_files_unchanged':{n:v==after['files'].get(n) for n,v in before['files'].items()}}
  dump(out/'cleanup.json',cleanup)
 try:
  result=subprocess.run([sys.executable,'-B',str(out/'code/analyze.py'),'--out',str(out)])
  if result.returncode:errors.append('independent audit rejected evidence')
 except Exception as e:errors.append(str(e))
 if errors:raise RuntimeError('; '.join(errors))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args();out=pathlib.Path(a.out).resolve()
 install_signals()
 if a.execute:asyncio.run(execute(out));sys.exit()
 from plan import make_plan
 out.mkdir(parents=True,exist_ok=False);(out/'code').mkdir();plan=make_plan();identity=model_identity();plan['backend_command']=backend_command(27);plan['backend_alias']=alias(27);plan['identity']={'model_sha256':identity['weights_sha256'],'tokenizer_sha256':identity['files']['tokenizer.json'],'template_sha256':identity['template_sha256']}
 for f in D.glob('*.py'):
  if f.name.startswith('test_'):continue
  shutil.copy2(f,out/'code'/f.name);plan['source_sha256'][f.name]=sha(f)
 dump(out/'plan.json',plan);dump(out/'freeze.json',{'plan_sha256':sha(out/'plan.json'),'source_sha256':plan['source_sha256'],'time_ns':time.time_ns()})
 exec_frozen([sys.executable,'-B',str(out/'code/run.py'),'--out',str(out),'--execute'])
