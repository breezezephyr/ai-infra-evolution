from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""Freeze before execute; run only frozen cases/source, keep raw failures, join own gateway."""
import argparse,asyncio,json,pathlib,hashlib,os,signal,socket,subprocess,sys,time,codecs,shutil
D=pathlib.Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(path,v):path.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def live(port):
 with socket.socket() as s:s.settimeout(.2);return s.connect_ex(('127.0.0.1',port))==0

async def execute(out,root):
 import httpx
 plan=json.loads((out/'plan.json').read_text())
 for name,h in plan['source_sha256'].items():assert sha(out/'code'/name)==h,(name,'source changed')
 assert live(plan['backend_port']) and not live(plan['gateway_port'])
 logs=(out/'gateway-server.log').open('w');proc=None;rows=[];health=[];error=None
 try:
  proc=subprocess.Popen([sys.executable,'-B',str(out/'code/serve_gateway.py'),'--out',str(out)],stdout=logs,stderr=logs,start_new_session=True)
  async with httpx.AsyncClient(timeout=40) as client:
   for _ in range(200):
    if proc.poll() is not None:raise RuntimeError('gateway crashed')
    try:
     if (await client.get(f'http://127.0.0.1:{plan["gateway_port"]}/health')).status_code==200:break
    except httpx.HTTPError:pass
    await asyncio.sleep(.05)
   else:raise RuntimeError('gateway not ready')
   for c in plan['cases']:
    base=f'http://127.0.0.1:{plan["gateway_port"]}'
    assert (await client.post(base+'/lab/reset')).status_code==200
    row={'case_id':c['case_id'],'request_id':None,'status':None,'raw':'','clock_domain':f'client-{os.getpid()}','started_ns':time.monotonic_ns(),'client_closed_intentionally':False}
    decoder=codecs.getincrementaldecoder('utf-8')();pending='';raw=[]
    try:
     async with client.stream('POST',base+'/generate',json={'case_id':c['case_id']}) as resp:
      row.update(request_id=resp.headers.get('x-request-id'),status=resp.status_code)
      async for chunk in resp.aiter_bytes():
       text=decoder.decode(chunk);raw.append(text);pending+=text
       if c.get('client_disconnect') and '"type":"content"' in pending:
        row['client_closed_intentionally']=True;row['client_close_ns']=time.monotonic_ns();break
    except Exception as e:row.update(error_type=type(e).__name__,error=str(e))
    row.update(raw=''.join(raw),ended_ns=time.monotonic_ns());rows.append(row);dump(out/'clients.json',rows)
    for _ in range(200):
     state=(await client.get(base+'/health')).json()
     if state['active']==0 and state['workers']==0:break
     await asyncio.sleep(.02)
    health.append({'case_id':c['case_id'],'state':state,'ns':time.monotonic_ns()});dump(out/'health.json',health)
    if state['active'] or state['workers']:raise RuntimeError('request worker did not join')
   # Allow engine abort snapshot to be appended; no further generation.
   await asyncio.sleep(.5)
  backend=root/'backend.jsonl'
  shutil.copy2(backend,out/'backend.jsonl')
  dump(out/'backend-snapshot.json',{'source':str(backend),'sha256':sha(backend),'model_identity_sha256':sha(root/'model-identity.json')})
  result=subprocess.run([sys.executable,'-B',str(out/'code/analyze.py'),'--out',str(out)])
  if result.returncode:error='independent audit rejected run'
 except BaseException as e:
  error=type(e).__name__+': '+str(e);dump(out/'run-error.json',{'error':error})
 finally:
  if proc and proc.poll() is None:
   proc.terminate()
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
  logs.close();dump(out/'gateway-cleanup.json',{'pid':proc.pid if proc else None,'exited':proc.poll() is not None if proc else None,'port_listening':live(plan['gateway_port'])})
 if error:raise RuntimeError(error)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--root',default=os.environ['P5_EXP_ROOT']);p.add_argument('--execute',action='store_true');a=p.parse_args();out=pathlib.Path(a.out).resolve()
 install_signals()
 if a.execute:asyncio.run(execute(out,pathlib.Path(a.root)));sys.exit()
 from gateway import make_plan
 out.mkdir(parents=True,exist_ok=False);(out/'code').mkdir();plan=make_plan();plan['model_identity']=json.loads((pathlib.Path(a.root)/'model-identity.json').read_text())
 for f in D.glob('*.py'):
  if f.name.startswith('test_'):continue
  shutil.copy2(f,out/'code'/f.name);plan['source_sha256'][f.name]=sha(f)
 dump(out/'plan.json',plan);dump(out/'freeze.json',{'plan_sha256':sha(out/'plan.json'),'source_sha256':plan['source_sha256'],'frozen_ns':time.time_ns()})
 cmd=[sys.executable,'-B',str(out/'code/run.py'),'--out',str(out),'--root',a.root,'--execute']
 exec_frozen(cmd)
