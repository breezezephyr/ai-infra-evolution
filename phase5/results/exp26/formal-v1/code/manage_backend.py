"""Start/stop only the recorded exp26 vLLM child; verify current ownership."""
import argparse,datetime,hashlib,json,os,pathlib,signal,socket,subprocess,time
p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop']);p.add_argument('--root',default='/opt/exp26-20261026-p5h');a=p.parse_args();root=pathlib.Path(a.root)
def dump(name,obj):(root/name).write_text(json.dumps(obj,indent=2)+'\n')
def port(n):
 with socket.socket() as s:s.settimeout(.2);return s.connect_ex(('127.0.0.1',n))==0
def gpu():return subprocess.check_output(['/usr/lib/wsl/lib/nvidia-smi','--query-gpu=name,memory.total,memory.used,utilization.gpu','--format=csv,noheader'],text=True).strip()
def alive(pid):return pathlib.Path('/proc')/str(pid)
def modelhash():return {n:hashlib.sha256((pathlib.Path('/opt/models/Qwen3-0.6B')/n).read_bytes()).hexdigest() for n in ['model.safetensors','tokenizer.json','tokenizer_config.json','config.json']}
if a.action=='start':
 assert not port(8026) and not port(8126),'exp26 ports in use'
 cmd=['/root/vllm-env/bin/vllm','serve','/opt/models/Qwen3-0.6B','--served-model-name','exp26-qwen3-0.6b','--host','127.0.0.1','--port','8026','--dtype','bfloat16','--max-model-len','2048','--max-num-seqs','4','--max-num-batched-tokens','4096','--gpu-memory-utilization','0.60','--enforce-eager','--disable-frontend-multiprocessing','--disable-log-requests','--generation-config','vllm','--middleware','backend_audit.AuditMiddleware']
 env=dict(os.environ,PYTHONPATH='/opt/p2/stub:'+str(root),VLLM_USE_V1='0',EXP26_AUDIT_PATH=str(root/'backend.jsonl'))
 with (root/'backend-server.log').open('w') as log:proc=subprocess.Popen(cmd,env=env,cwd=root,stdout=log,stderr=log,start_new_session=True)
 info={'pid':proc.pid,'command':cmd,'gpu_before':gpu(),'model_files_before':modelhash(),'source_sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in root.glob('*.py')},'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};dump('backend-startup.json',info);print(json.dumps({'pid':proc.pid,'gpu':info['gpu_before']}))
else:
 info=json.loads((root/'backend-startup.json').read_text());pid=info['pid'];path=alive(pid)
 cmdline=(path/'cmdline').read_bytes().replace(b'\0',b' ').decode() if path.exists() else ''
 if path.exists():
  assert 'exp26-qwen3-0.6b' in cmdline and '8026' in cmdline,'PID ownership mismatch'
  os.killpg(pid,signal.SIGTERM)
  for _ in range(200):
   if not path.exists() or (path/'stat').read_text().split()[2]=='Z':break
   time.sleep(.05)
  else:os.killpg(pid,signal.SIGKILL)
 time.sleep(.2)
 exists=path.exists() and (path/'stat').read_text().split()[2]!='Z'
 hashes=modelhash();cleanup={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':pid,'pid_exists':exists,'port_listening':{str(n):port(n) for n in [8026,8126]},'gpu':gpu(),'model_files_unchanged':{n:h==info['model_files_before'][n] for n,h in hashes.items()}}
 dump('cleanup.json',cleanup);print(json.dumps(cleanup))
 assert not exists and not any(cleanup['port_listening'].values()) and all(cleanup['model_files_unchanged'].values())
