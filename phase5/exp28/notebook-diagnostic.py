"""Run once in a new Notebook cell; no model reload or service restart."""
import os, sys, json, time, hashlib, inspect, platform, subprocess
import importlib.metadata as p5_md
from pathlib import Path
import torch, requests

P5_RUN_ID = 'exp28-kaggle-20261109-ef35f831'
P5_DIR = Path('/kaggle/working') / P5_RUN_ID
P5_DIR.mkdir(exist_ok=True)
p5_versions = {}
for p5_package in ['torch','diffusers','transformers','accelerate','bitsandbytes','gradio','fastapi','uvicorn']:
    p5_versions[p5_package] = p5_md.version(p5_package)
p5_gpus = []
for p5_i in range(torch.cuda.device_count()):
    p5_free, p5_total = torch.cuda.mem_get_info(p5_i)
    p5_gpus.append({'index':p5_i, 'name':torch.cuda.get_device_name(p5_i),
                    'total_bytes':p5_total, 'free_bytes':p5_free,
                    'allocated_bytes':torch.cuda.memory_allocated(p5_i)})
p5_local = requests.get(qwen_local_url.rstrip('/')+'/health',
                        headers={'Authorization':'Bearer '+QWEN_API_KEY}, timeout=15)
p5_snapshots = sorted(p.name for p in (Path(CACHE)/'models--Qwen--Qwen-Image-2.1/snapshots').glob('*') if p.is_dir())
p5_sources = {}
for p5_name in ['_qwen_api_raw_generate','generate_image','qwen_generate','qwen_health','require_api_key']:
    try:
        p5_source = inspect.getsource(globals()[p5_name])
        if QWEN_API_KEY in p5_source:
            raise RuntimeError('Credential detected in source; refusing to export')
        (P5_DIR/(p5_name+'.py')).write_text(p5_source)
        p5_sources[p5_name] = hashlib.sha256(p5_source.encode()).hexdigest()
    except (OSError, TypeError):
        p5_sources[p5_name] = None
p5_smi = subprocess.run(['nvidia-smi','--query-gpu=index,name,driver_version,memory.total,memory.used,utilization.gpu','--format=csv'],capture_output=True,text=True,check=True).stdout
(P5_DIR/'nvidia-smi-before.csv').write_text(p5_smi)
(P5_DIR/'pip-list.json').write_text(subprocess.run([sys.executable,'-m','pip','list','--format=json'],capture_output=True,text=True,check=True).stdout)
p5_before_files = []
for p5_file in sorted(Path('/kaggle/working/qwen-image-output').glob('*')):
    if p5_file.is_file():
        p5_before_files.append({'name':p5_file.name,'bytes':p5_file.stat().st_size,'sha256':hashlib.sha256(p5_file.read_bytes()).hexdigest()})
p5_environment = {'run_id':P5_RUN_ID,'observed_at_unix':time.time(),'python':sys.version,
    'versions':p5_versions,'torch_cuda_runtime':torch.version.cuda,'gpus':p5_gpus,
    'cpu_logical_count':os.cpu_count(),'cpu_affinity_count':len(os.sched_getaffinity(0)),
    'placement':pipe.hf_device_map,'snapshot_revisions_present':p5_snapshots,
    'only_one_cached_snapshot_seen':len(p5_snapshots)==1,
    'active_model_revision_verified':False,
    'dependency_vcs_commit':{p5_p:(json.loads(p5_md.distribution(p5_p).read_text('direct_url.json') or '{}').get('vcs_info') or {}).get('commit_id') for p5_p in ['diffusers','transformers']},
    'weight_files_rehashed':False,'source_sha256':p5_sources,
    'local_health_status':p5_local.status_code,'local_health':p5_local.json(),
    'generation_lock_busy':_qwen_generation_lock.locked(),
    'available_api_slots_observed':getattr(_qwen_api_slots,'_value',None),
    'gradio_is_running':bool(qwen_api_demo.is_running),
    'public_url':qwen_public_url,'credential_export_exists':Path('/kaggle/working/qwen-api-access.json').exists(),
    'existing_output_files':p5_before_files}
(P5_DIR/'environment-before.json').write_text(json.dumps(p5_environment,indent=2))
print('P5_DIAGNOSTIC '+json.dumps({k:v for k,v in p5_environment.items() if k!='existing_output_files'}))
