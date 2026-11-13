#!/usr/bin/env python3
"""每个压测窗口的服务端峰值/增量（Prometheus on wy，job=vllm-bench）。
用法：python3 prom_windows.py [--prefix exp5] [--md out.md]
列：running 峰值、waiting 峰值、KV 峰值%、抢占次数、服务端完成条数(按 finish_reason)、prompt/gen token 增量
"""
import json,glob,os,sys,subprocess,shlex
D=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(D,'results')
a=sys.argv[1:]; pref=a[a.index('--prefix')+1] if '--prefix' in a else 'exp5'; md=a[a.index('--md')+1] if '--md' in a else None
runs=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(R,f'{pref}*.json')))]
J='{job="vllm-bench"}'
MAXQ={'running':f'vllm:num_requests_running{J}','waiting':f'vllm:num_requests_waiting{J}','kv':f'vllm:gpu_cache_usage_perc{J}'}
DELTA={'preempt':f'vllm:num_preemptions_total{J}','prompt_tok':f'vllm:prompt_tokens_total{J}','gen_tok':f'vllm:generation_tokens_total{J}'}
lines=[]
for r in runs:
    s=int(r['prom_start']); e=int(r['prom_end'])+8; w=e-s
    for k,q in MAXQ.items():
        lines.append(f'echo "{r["name"]}|{k}|$(curl -s -G localhost:9090/api/v1/query --data-urlencode {shlex.quote(f"query=max_over_time({q}[{w}s])")} --data-urlencode time={e})"')
    for k,q in DELTA.items():
        lines.append(f'echo "{r["name"]}|{k}|$(curl -s -G localhost:9090/api/v1/query --data-urlencode {shlex.quote(f"query=increase({q}[{w}s])")} --data-urlencode time={e})"')
    lines.append(f'echo "{r["name"]}|finish|$(curl -s -G localhost:9090/api/v1/query --data-urlencode {shlex.quote(f"query=increase(vllm:request_success_total{J}[{w}s])")} --data-urlencode time={e})"')
out=subprocess.run(['ssh','wy','bash','-s'],input='\n'.join(lines),capture_output=True,text=True).stdout
val={}
for ln in out.splitlines():
    if '|' not in ln: continue
    name,k,js=ln.split('|',2)
    try: res=json.loads(js)['data']['result']
    except Exception: res=[]
    if k=='finish': val[(name,k)]={x['metric'].get('finished_reason','?'):round(float(x['value'][1])) for x in res}
    else: val[(name,k)]=float(res[0]['value'][1]) if res else float('nan')
hdr='| 窗口 | 客户端完成/错误 | running 峰 | waiting 峰 | KV 峰 | 抢占 | 服务端完成(reason) | prompt tok | gen tok |'
rows=[hdr,'|'+'---|'*9]
for r in runs:
    n=r['name']; g=lambda k: val.get((n,k),float('nan'))
    if 'classes' in r:  # mix.py 汇总（exp6+）
        comp=sum(c['done'] for c in r['classes'].values()); errs=sum(c['err'] for c in r['classes'].values())
    else:
        comp=r['completed']; errs=len([x for x in r.get('errors',[]) if x])
    rows.append(f"| {n} | {comp} / {errs} | {g('running'):.0f} | {g('waiting'):.0f} | {g('kv')*100:.0f}% | {g('preempt'):.0f} | {val.get((n,'finish'),{})} | {g('prompt_tok'):.0f} | {g('gen_tok'):.0f} |")
print('\n'.join(rows))
if md: open(md,'w').write('\n'.join(rows)+'\n'); print('->',md)
