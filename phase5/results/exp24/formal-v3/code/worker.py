"""One real Store client; stdout reserved for bounded JSON command/reply IPC."""
import sys, os, json, time, hashlib, pathlib
from audit import request_for,request_digest
wire=os.fdopen(os.dup(1),'w',buffering=1)
os.dup2(2,1)
from mooncake.store import MooncakeDistributedStore
planpath=pathlib.Path(sys.argv[1]);planbytes=planpath.read_bytes();plan=json.loads(planbytes)
planhash=hashlib.sha256(planbytes).hexdigest();workerhash=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
assert workerhash==plan['code_sha256']['worker.py']
cases={c['id']:c for c in plan['cases']}
store=MooncakeDistributedStore()

def payload(seed,size):
    return hashlib.shake_256(seed.encode()).digest(size)

for line in sys.stdin:
    envelope=json.loads(line);case=cases[envelope['id']]
    assert envelope['plan_sha256']==planhash and envelope['request_sha256']==request_digest(case)
    c=request_for(case)
    data=payload(c['seed'],c['size']) if c['op']=='put' else None
    t=time.perf_counter_ns()
    try:
        op=c['op']
        if op=='setup':
            v=store.setup(c['hostname'],'P2PHANDSHAKE',c['global_size'],c['buffer_size'],'tcp','',c['master'])
        elif op=='put': v=store.put(c['key'],data)
        elif op=='remove': v=store.remove(c['key'],True)
        else: v=getattr(store,op)(*([c['key']] if 'key' in c else []))
        elapsed=(time.perf_counter_ns()-t)/1e6
        r={'id':c['id'],'op':op,'complete':True,'latency_ms':elapsed}
        if isinstance(v,bytes): r.update(kind='bytes',size=len(v),sha256=hashlib.sha256(v).hexdigest())
        elif isinstance(v,int): r.update(kind='code',value=v)
        elif v is None: r['kind']='none'
        else: r.update(kind='other',value=repr(v))
    except Exception as e:
        r={'id':c['id'],'op':c['op'],'complete':True,'kind':'exception',
           'exception_type':type(e).__name__,'message':str(e),'latency_ms':(time.perf_counter_ns()-t)/1e6}
    r.update(client=c['client'],stage=c['stage'],key=c.get('key'),pid=os.getpid(),
             request_sha256=request_digest(case),plan_sha256=planhash,worker_sha256=workerhash,
             started_perf_ns=t,finished_perf_ns=time.perf_counter_ns())
    wire.write(json.dumps(r)+'\n');wire.flush()
    if c['op']=='close': break
