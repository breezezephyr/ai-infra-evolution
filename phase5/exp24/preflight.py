"""Bounded actual API discovery only; not part of the formal denominator."""
import os, subprocess, time, json, pathlib, socket
R=pathlib.Path('/opt/exp24-20261026-p5f')
log=(R/'preflight-master.log').open('w')
p=subprocess.Popen([str(R/'venv/bin/mooncake_master'),'--rpc_address=127.0.0.1','--rpc_port=50240','--metrics_port=9024','--enable_http_metadata_server=false'],stdout=log,stderr=log)
try:
    time.sleep(2)
    from mooncake.store import MooncakeDistributedStore
    s=MooncakeDistributedStore()
    def run(name,*args):
        t=time.perf_counter()
        try:
            v=getattr(s,name)(*args)
            print(json.dumps({'op':name,'value':repr(v),'type':type(v).__name__,'ms':(time.perf_counter()-t)*1000}),flush=True)
        except Exception as e: print(json.dumps({'op':name,'error':repr(e)}),flush=True)
    run('setup','127.0.0.1:50241','P2PHANDSHAKE',128*1024*1024,32*1024*1024,'tcp','','127.0.0.1:50240')
    run('put','exp24-preflight-a',b'abcd')
    run('get','exp24-preflight-a')
    run('put','exp24-preflight-a',b'new')
    run('get','exp24-preflight-a')
    run('is_exist','exp24-preflight-a')
    run('remove','exp24-preflight-a',True)
    run('is_exist','exp24-preflight-a')
    run('get','exp24-preflight-a')
    run('remove','exp24-preflight-a',True)
    p.terminate();p.wait(timeout=10)
    run('is_exist','exp24-preflight-a')
    run('get','exp24-preflight-a')
    run('close')
finally:
    if p.poll() is None: p.kill();p.wait()
    log.close()
