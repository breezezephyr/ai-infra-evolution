"""Freeze then execute archived code; output directories must be new."""
import json,hashlib,pathlib,sys,subprocess,argparse,datetime
D=pathlib.Path(__file__).resolve().parent

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(seed,n): return hashlib.sha256(hashlib.shake_256(seed.encode()).digest(n)).hexdigest()

def make_plan():
    p={'schema':1,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'scope':'real non-CUDA Mooncake single-host TCP; no model KV, GPU, RDMA or HA',
       'package':'mooncake-transfer-engine-non-cuda','version':'0.3.13.post1',
       'wheel_sha256':'892fd0ee77d736fc8d625981c485a43282dbdbc0926b95f05c1cadd8b0debe51',
       'master_port':50240,'metrics_port':9024,'client_ports':[50241,50242,50243],
       'global_size':128*1024**2,'buffer_size':32*1024**2,'deadline_seconds':25,
       'revision':'formal-v2 cross-process reader; v1 same-process retained separately',
       'sizes':[1,4096,65536,1048576],'repeats':10,'cases':[],'steps':[]}
    def action(op,**kw): p['steps'].append({'action':op,**kw})
    def add(op,key=None,kind='code',code=0,client='A',**kw):
        i=f'op-{len(p["cases"])+1:03d}'
        e={'id':i,'op':op,'client':('B' if op=='get' and client=='A' else client),'expected_kind':kind,**kw}
        if key is not None: e['key']=key
        if kind=='code': e['code']=code
        if kind=='bytes': e['sha256']=digest(kw['seed'],kw['size']) if 'seed' in kw else hashlib.sha256(b'').hexdigest()
        p['cases'].append(e);action('call',id=i)
    action('start_master');action('start_client',client='A')
    add('setup',hostname='127.0.0.1:50241',global_size=p['global_size'],buffer_size=p['buffer_size'],master='127.0.0.1:50240')
    action('start_client',client='B')
    add('setup',client='B',hostname='127.0.0.1:50242',global_size=0,buffer_size=p['buffer_size'],master='127.0.0.1:50240')
    miss='exp24-formal-v2/missing'
    add('get',miss,kind='bytes',size=0);add('is_exist',miss,code=0);add('remove',miss,code=-704)
    for size in p['sizes']:
        for rep in range(p['repeats']):
            key=f'exp24-formal-v2/data/{size}/{rep}';seed=f'exp24:{size}:{rep}'
            add('put',key,size=size,seed=seed,timing_group=f'{size}:put')
            add('get',key,kind='bytes',size=size,seed=seed,timing_group=f'{size}:get')
            add('is_exist',key,code=1)
    dup='exp24-formal-v2/duplicate'
    for label,seed,size in [('initial','duplicate-original',4096),('identical','duplicate-original',4096),('same-size','different-content',4096),('different-size','other-length',8192)]:
        add('put',dup,size=size,seed=seed,duplicate_variant=label)
        add('get',dup,kind='bytes',size=4096,seed='duplicate-original',duplicate_variant=label)
    for size in p['sizes']:
        for rep in range(p['repeats']):
            key=f'exp24-formal-v2/data/{size}/{rep}'
            add('remove',key,timing_group=f'{size}:remove');add('is_exist',key,code=0)
    add('remove',dup);add('is_exist',dup,code=0)
    survivor='exp24-formal-v2/survivor'
    add('put',survivor,size=65536,seed='survivor');add('get',survivor,kind='bytes',size=65536,seed='survivor')
    action('stop_master')
    add('get',survivor,kind='bytes',size=0,stage='master-down')
    add('is_exist',survivor,kind='observation',stage='master-down')
    add('put','exp24-formal-v2/down-write',kind='observation',size=32,seed='down',stage='master-down')
    action('start_master');action('sleep',seconds=3)
    add('is_exist',survivor,kind='observation',stage='restart-existing-client-immediate')
    add('get',survivor,kind='observation',stage='restart-existing-client-immediate')
    action('sleep',seconds=12)
    add('is_exist',survivor,kind='observation',stage='restart-existing-client-after12s')
    add('get',survivor,kind='observation',stage='restart-existing-client-after12s')
    action('start_client',client='C')
    add('setup',client='C',hostname='127.0.0.1:50243',global_size=16*1024**2,buffer_size=16*1024**2,master='127.0.0.1:50240')
    add('is_exist',survivor,kind='observation',client='C',stage='restart-fresh-client')
    add('get',survivor,kind='observation',client='C',stage='restart-fresh-client')
    recovery='exp24-formal-v2/recovery'
    add('put',recovery,client='C',size=4096,seed='recovery')
    add('get',recovery,client='C',kind='bytes',size=4096,seed='recovery')
    add('remove',recovery,client='C');add('is_exist',recovery,client='C',code=0)
    # Named-key cleanup evidence, including keys whose restart outcomes are exploratory.
    for key in (survivor,'exp24-formal-v2/down-write'):
        add('remove',key,client='C',kind='observation',stage='cleanup')
        add('is_exist',key,client='C',code=0,stage='cleanup')
    add('close',client='A');add('close',client='B');add('close',client='C');action('stop_master')
    return p

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args()
    out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
    code=out/'code';code.mkdir()
    for name in ('freeze.py','runner.py','worker.py','audit.py'):
        (code/name).write_bytes((D/name).read_bytes())
    plan=make_plan();plan['code_sha256']={x.name:sha(x) for x in sorted(code.glob('*.py'))}
    (out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    subprocess.run([sys.executable,'-B',str(code/'runner.py'),'--out',str(out)],check=True)
