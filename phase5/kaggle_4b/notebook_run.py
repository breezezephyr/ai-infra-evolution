"""Run the pinned suite in a foreground Notebook cell, then archive its evidence."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time,urllib.request,shutil
BASE_URL='https://raw.githubusercontent.com/breezezephyr/ai-infra-evolution/'
OUT=Path('/kaggle/working/p5-4b-20261113');CODE=Path('/kaggle/working/kaggle_4b')
OUT.mkdir(parents=True,exist_ok=True)
def fetch(commit,path,digest):
 data=urllib.request.urlopen(BASE_URL+commit+'/phase5/kaggle_4b/'+path,timeout=60).read()
 if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Pinned source checksum mismatch')
 return data
if (OUT/'validation').exists():raise RuntimeError('Existing validation evidence; refuse another run in this directory')
bootstrap=OUT/'bootstrap.py';bootstrap.write_bytes(fetch('8135e6fb17cc551d558f3e2686cd584a50ac39d5','bootstrap.py','e97553a3d8e9accded313fbe5df8af6022d93e5e27c200e3d926c03c40b61408'))
started=time.time();rc=None
try:
 print('Preparing pinned Python 3.11 / vLLM 0.8.5 / Qwen3-4B',flush=True)
 with (OUT/'setup-py311.log').open('w') as stream:subprocess.run([sys.executable,'-u',str(bootstrap)],stdout=stream,stderr=subprocess.STDOUT,check=True)
 data=fetch('ec1b74d7a82e2f5e0ec4abed87e854b6ef836d4d','code-bundle.json','7652debdee69ad49210f8892f80236ab1cd275906048b9658a68333d246f8d22')
 files=json.loads(data)['files']
 if CODE.exists():raise RuntimeError('Code extraction target already exists')
 for f in files:
  p=Path(f['path']);b=f['content'].encode()
  if p.is_absolute() or '..' in p.parts or hashlib.sha256(b).hexdigest()!=f['sha256']:raise RuntimeError('Unsafe bundle entry')
  dst=CODE/p;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)
 py='/kaggle/temp/p5-4b/venv311/bin/python'
 cmd=[py,'-u',str(CODE/'run_suite.py'),'--out',str(OUT/'validation'),'--prepared',str(OUT/'model-prepared.json'),'--python',py,'--vllm-bin','/kaggle/temp/p5-4b/venv311/bin/vllm']
 print('Running frozen 42 / 17 / 42 scenarios; logs remain in the evidence directory.',flush=True)
 with (OUT/'validation-supervisor.log').open('w') as stream:rc=subprocess.run(cmd,cwd=CODE,stdout=stream,stderr=subprocess.STDOUT).returncode
 print('Suite exit:',rc,flush=True)
 if (OUT/'validation/suite-summary.json').exists():print((OUT/'validation/suite-summary.json').read_text(),flush=True)
finally:
 (OUT/'notebook-supervisor.json').write_text(json.dumps({'started':started,'finished':time.time(),'returncode':rc}))
 archive=shutil.make_archive('/kaggle/working/p5-4b-evidence-'+str(time.time_ns()),'zip',root_dir=OUT)
 print('EVIDENCE_ARCHIVE',archive,hashlib.sha256(Path(archive).read_bytes()).hexdigest(),flush=True)
 from IPython.display import display,FileLink
 display(FileLink(archive))
if rc!=0:raise RuntimeError('Suite failed; inspect the archived raw logs, never reuse its values as accepted evidence')
