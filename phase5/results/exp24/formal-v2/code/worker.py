"""One real Store client; stdout reserved for bounded JSON command/reply IPC."""
import sys, os, json, time, hashlib
wire=os.fdopen(os.dup(1),'w',buffering=1)
os.dup2(2,1)
from mooncake.store import MooncakeDistributedStore
store=MooncakeDistributedStore()

def payload(seed,size):
    return hashlib.shake_256(seed.encode()).digest(size)

for line in sys.stdin:
    c=json.loads(line)
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
    wire.write(json.dumps(r)+'\n');wire.flush()
    if c['op']=='close': break
