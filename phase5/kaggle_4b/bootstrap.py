"""Prepare a pinned Kaggle Qwen3-4B/vLLM environment, without model generation."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
BASE=Path('/kaggle/temp/p5-4b');OUT=Path('/kaggle/working/p5-4b-20261113')
BASE.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
os.environ.update(HF_HOME=str(BASE/'hf'),HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1',CUDA_VISIBLE_DEVICES='0',TOKENIZERS_PARALLELISM='false')
def run(cmd):
 print('STEP',cmd[:4],flush=True);subprocess.run(cmd,check=True)
try:
 hardware=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.total,memory.free,driver_version','--format=csv'],text=True)
 (OUT/'hardware-before.txt').write_text(hardware);print(hardware,flush=True)
 if (OUT/'model-prepared.json').exists():
  print('Already prepared; no generation requested.',flush=True);sys.exit(0)
 venv=BASE/'venv311'
 if not (venv/'bin/python').exists():
  uv=shutil.which('uv')
  if not uv:raise RuntimeError('uv is required to create the pinned Python 3.11 environment')
  run([uv,'venv','--python','3.11','--seed',str(venv)])
 python=str(venv/'bin/python')
 run([python,'-m','pip','install','--disable-pip-version-check','--no-cache-dir','vllm==0.8.5','transformers==4.51.3','huggingface_hub>=0.30,<1.0','numpy<2','httpx==0.28.1','pytest==8.3.5','matplotlib','pillow'])
 downloader=r'''
from pathlib import Path
import hashlib,json,importlib.metadata as md,torch
from huggingface_hub import snapshot_download
assert torch.cuda.is_available(), 'CUDA unavailable; CPU fallback forbidden'
assert torch.cuda.mem_get_info(0)[0]>10*1024**3,'GPU0 has less than 10GiB free'
repo='Qwen/Qwen3-4B';revision='1cfa9a7208912126459214e8b04321603b3df60c'
root=Path(snapshot_download(repo,revision=revision,token=False,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja'],max_workers=4));files=[]
for p in sorted(root.rglob('*')):
 if p.is_file():
  h=hashlib.sha256()
  with p.open('rb') as stream:
   for b in iter(lambda:stream.read(8*1024**2),b''):h.update(b)
  files.append({'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'sha256':h.hexdigest()})
packages={p:md.version(p) for p in ['vllm','torch','transformers','tokenizers','huggingface_hub','fastapi','uvicorn','httpx']}
prepared={'repo':repo,'revision':revision,'model_path':str(root),'files':files,'packages':packages,'dtype':'float16','visible_gpu':0,'gpu':torch.cuda.get_device_name(0),'generation_requests':0}
Path('/kaggle/working/p5-4b-20261113/model-prepared.json').write_text(json.dumps(prepared,indent=2))
print('PREPARED',json.dumps({k:v for k,v in prepared.items() if k!='files'}),flush=True)
'''
 run([python,'-u','-c',downloader])
 (OUT/'setup-status.json').write_text(json.dumps({'prepared':True,'at':time.time(),'generation_requests':0}))
except BaseException as exc:
 if isinstance(exc,SystemExit):raise
 (OUT/'setup-status.json').write_text(json.dumps({'prepared':False,'error_type':type(exc).__name__,'at':time.time(),'generation_requests':0}));raise
