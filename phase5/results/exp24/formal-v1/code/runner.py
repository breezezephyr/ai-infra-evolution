"""Execute a read-back frozen plan against owned master/clients with hard IPC deadlines."""
import os,sys,json,pathlib,subprocess,select,time,socket,hashlib,signal,platform,importlib.metadata,argparse
from audit import audit_records


def listening(port):
    with socket.socket() as s:
        s.settimeout(.2)
        return s.connect_ex(('127.0.0.1',port))==0


def run(out):
    planbytes=(out/'plan.json').read_bytes();p=json.loads(planbytes)
    for name,digest in p['code_sha256'].items():
        if hashlib.sha256((out/'code'/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('code hash mismatch: '+name)
    if importlib.metadata.version(p['package'])!=p['version']:raise ValueError('package version changed')
    for port in [p['master_port'],p['metrics_port'],*p['client_ports']]:
        if listening(port): raise RuntimeError(f'port {port} already listening')
    (out/'environment.json').write_text(json.dumps({'uname':platform.uname()._asdict(),
        'python':sys.version,'package':p['package'],'version':importlib.metadata.version(p['package']),
        'plan_sha256':hashlib.sha256(planbytes).hexdigest(),'executed_code_sha256':p['code_sha256'],
        'clock':'perf_counter_ns around individual Python Store call in same worker',
        'gpu_used':False,'transport':'tcp loopback','master_ha':False,'snapshot_restore':False,
        'ssd_offload':False},indent=2)+'\n')
    master=None;clients={};logs=[];events=[];records=[];owned=[];generation=0
    def event(action,**kw):
        events.append({'action':action,'parent_monotonic_ns':time.monotonic_ns(),**kw})
        (out/'lifecycle.json').write_text(json.dumps(events,indent=2)+'\n')
    def stop(proc,label):
        if proc is None:return
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        event('stopped',label=label,pid=proc.pid,returncode=proc.returncode)
    def start_master():
        nonlocal master,generation
        generation+=1
        f=(out/f'master-{generation}.log').open('w');logs.append(f)
        cmd=[str(pathlib.Path(sys.executable).parent/'mooncake_master'),
             '--rpc_address=127.0.0.1',f'--rpc_port={p["master_port"]}',f'--metrics_port={p["metrics_port"]}',
             '--enable_ha=false','--enable_snapshot=false','--enable_snapshot_restore=false','--enable_offload=false']
        master=subprocess.Popen(cmd,stdout=f,stderr=f,start_new_session=True);owned.append(master)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and not listening(p['master_port']):
            if master.poll() is not None:raise RuntimeError('master exited')
            time.sleep(.05)
        if not listening(p['master_port']):raise RuntimeError('master not ready')
        event('master_started',pid=master.pid,cmd=cmd,generation=generation)
    def start_client(label):
        f=(out/f'client-{label}.log').open('w');logs.append(f)
        proc=subprocess.Popen([sys.executable,'-B',str(out/'code'/'worker.py')],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=f,text=True,bufsize=1,start_new_session=True)
        clients[label]=proc;owned.append(proc);event('client_started',client=label,pid=proc.pid)
    def call(c):
        proc=clients[c['client']];deadline=time.monotonic()+p['deadline_seconds']
        cmd={k:v for k,v in c.items() if k not in ('expected_kind','code','sha256','client','timing_group','stage','duplicate_variant')}
        try:
            if proc.poll() is not None:raise RuntimeError('worker already exited')
            proc.stdin.write(json.dumps(cmd)+'\n');proc.stdin.flush()
            ready,_,_=select.select([proc.stdout],[],[],max(0,deadline-time.monotonic()))
            if not ready:
                stop(proc,'timeout-'+c['client'])
                r={'id':c['id'],'op':c['op'],'complete':False,'kind':'timeout','latency_ms':None,
                   'censor_limit_ms':p['deadline_seconds']*1000}
            else:
                line=proc.stdout.readline()
                if not line:raise RuntimeError('worker EOF')
                r=json.loads(line)
                if r['id']!=c['id']:raise RuntimeError('reply correlation mismatch')
        except Exception as e:
            r={'id':c['id'],'op':c['op'],'complete':False,'kind':'transport_error',
               'exception_type':type(e).__name__,'message':str(e),'latency_ms':None}
        r.update(client=c['client'],stage=c.get('stage','normal'))
        records.append(r)
        with (out/'records.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
    try:
        cases={c['id']:c for c in p['cases']}
        for step in p['steps']:
            if step['action']=='start_master':start_master()
            elif step['action']=='stop_master':stop(master,'master');master=None
            elif step['action']=='start_client':start_client(step['client'])
            elif step['action']=='sleep':event('sleep',seconds=step['seconds']);time.sleep(step['seconds'])
            elif step['action']=='call':call(cases[step['id']])
            else:raise ValueError('unknown action')
        report=audit_records(p,records)
        # Independently serialized raw rows are the audit input, not an in-memory success counter.
        raw=[json.loads(x) for x in (out/'records.jsonl').read_text().splitlines()]
        if audit_records(p,raw)!=report:raise RuntimeError('raw readback mismatch')
        (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='outcomes'}),flush=True)
    finally:
        for label,proc in clients.items():stop(proc,'client-'+label)
        stop(master,'master-final')
        time.sleep(.2)
        cleanup={'owned_pids':[x.pid for x in owned],'all_owned_exited':all(x.poll() is not None for x in owned),
                 'ports':{str(port):listening(port) for port in [p['master_port'],p['metrics_port'],*p['client_ports']]},
                 'key_cleanup_readback':'see named cleanup is_exist rows and 40 normal is_exist-after-remove rows',
                 'plan_unchanged':hashlib.sha256((out/'plan.json').read_bytes()).hexdigest()==hashlib.sha256(planbytes).hexdigest()}
        (out/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n')
        for f in logs:f.close()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();run(pathlib.Path(a.out).resolve())
