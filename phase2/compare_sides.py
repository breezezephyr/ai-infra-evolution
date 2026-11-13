#!/usr/bin/env python3
"""两面对上：客户端 bench JSON（vllm bench serve --save-result）vs 服务端 Prometheus 直方图。
每个窗口：服务端 mean = (sum@end - sum@start)/(count@end - count@start)，job=vllm-bench。
用法：.venv/bin/python compare_sides.py [--prefix exp2] [--md out.md]
"""
import json,glob,os,sys,subprocess,shlex
D=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(D,'results')
pref=None; md=None
a=sys.argv[1:]
for i,x in enumerate(a):
    if x=='--prefix': pref=a[i+1]
    if x=='--md': md=a[i+1]
M=['request_queue_time_seconds','request_prefill_time_seconds','request_decode_time_seconds',
   'request_inference_time_seconds','time_to_first_token_seconds','time_per_output_token_seconds','e2e_request_latency_seconds']
runs=[]
for f in sorted(glob.glob(os.path.join(R,'exp*.json'))):
    r=json.load(open(f)); n=r['name']
    if pref and not n.startswith(pref): continue
    runs.append(r)
# 一次 ssh 把所有点查回来
lines=[]
for r in runs:
    s=int(r['prom_start']); e=int(r['prom_end'])+8
    for m in M:
        for k in ('sum','count'):
            for t in (s,e):
                q=f'vllm:{m}_{k}{{job="vllm-bench"}}'
                lines.append(f'echo "{r["name"]}|{m}|{k}|{t}|$(curl -s -G localhost:9090/api/v1/query --data-urlencode {shlex.quote("query="+q)} --data-urlencode time={t})"')
out=subprocess.run(['ssh','wy','bash','-s'],input='\n'.join(lines),capture_output=True,text=True).stdout
val={}
for ln in out.splitlines():
    if '|' not in ln: continue
    name,m,k,t,js=ln.split('|',4)
    try: res=json.loads(js)['data']['result']; v=float(res[0]['value'][1]) if res else 0.0
    except Exception: v=0.0
    val[(name,m,k,int(t))]=v
def srv(r,m):
    s=int(r['prom_start']); e=int(r['prom_end'])+8
    ds=val[(r['name'],m,'sum',e)]-val[(r['name'],m,'sum',s)]; dc=val[(r['name'],m,'count',e)]-val[(r['name'],m,'count',s)]
    if dc<=0: # 计数器在窗口内重置（进程刚起）：直接用 end 值
        ds=val[(r['name'],m,'sum',e)]; dc=val[(r['name'],m,'count',e)]
    return (ds/dc*1000 if dc else float('nan')), dc
rows=[]
for r in runs:
    inp=r['total_input_tokens']/r['completed']; outl=r['total_output_tokens']/r['completed']
    q,_=srv(r,M[0]); p,_=srv(r,M[1]); d,_=srv(r,M[2]); inf,_=srv(r,M[3]); st,cnt=srv(r,M[4]); stp,_=srv(r,M[5]); se,_=srv(r,M[6])
    c_ttft=r['mean_ttft_ms']; c_tpot=r['mean_tpot_ms']; c_e2e=r['mean_e2el_ms']
    rows.append(dict(name=r['name'],conc=int(r['max_concurrency']),inp=int(inp),out=int(outl),n=r['completed'],srv_n=int(cnt),
        c_ttft=c_ttft,s_queue=q,s_prefill=p,s_ttft=st,ttft_gap=c_ttft-st,
        c_tpot=c_tpot,s_tpot=stp,c_e2e=c_e2e,s_e2e=se,e2e_gap=c_e2e-se,s_decode=d,
        prefill_us_tok=p/inp*1000))
hdr=['name','conc','inp','out','n','srv_n','c_ttft','s_queue','s_prefill','s_ttft','ttft_gap','c_tpot','s_tpot','c_e2e','s_e2e','e2e_gap','prefill_us_tok']
fmt=lambda v: f'{v:.1f}' if isinstance(v,float) else str(v)
w=[max(len(h),max(len(fmt(x[h])) for x in rows)) for h in hdr]
print(' '.join(h.ljust(x) for h,x in zip(hdr,w)))
for x in rows: print(' '.join(fmt(x[h]).ljust(z) for h,z in zip(hdr,w)))
# 客户端拟合：TTFT ~ a + b·input（exp2 每个预算一条线）
def linfit(xs,ys):
    n=len(xs); mx=sum(xs)/n; my=sum(ys)/n
    sxx=sum((x-mx)**2 for x in xs); sxy=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    b=sxy/sxx; a=my-b*mx; ss=sum((y-my)**2 for y in ys); sr=sum((y-(a+b*x))**2 for x,y in zip(xs,ys))
    return a,b,1-sr/ss if ss else 1
print('\n== 客户端 TTFT ~ 截距 + 斜率×input（exp2，并发 4，每个预算一条线）')
for bt in ('bt2048','bt8192'):
    xs=[];ys=[];ss=[]
    for r in runs:
        if r['name'].startswith('exp2-'+bt):
            for i,t in zip(r['input_lens'],r['ttfts']): xs.append(i); ys.append(t*1000)
    if len(xs)>2:
        a,b,r2=linfit(xs,ys); print(f'  {bt}: TTFT ≈ {a:.0f} ms + {b*1000:.0f} µs × input  (R²={r2:.2f})  per-request n={len(xs)}')
print('\n== 服务端 prefill 每 token（prefill_time/input，µs/tok）')
for x in rows:
    if x['name'].startswith('exp2') or x['name']=='exp1-c1': print(f"  {x['name']:22s} {x['prefill_us_tok']:.0f} µs/tok  (并发 {x['conc']}，一次 prefill 算的是整批同时在搬)")
if md:
    with open(md,'w') as f:
        f.write('| 窗口 | 并发 | in/out | 客户端 TTFT | 服务端 排队 | 服务端 prefill | 服务端 TTFT | 差(地板) | 客户端 TPOT | 服务端 TPOT | 客户端 e2e | 服务端 e2e | 差 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n')
        for x in rows:
            f.write(f"| {x['name']} | {x['conc']} | {x['inp']}/{x['out']} | {x['c_ttft']:.0f} | {x['s_queue']:.0f} | {x['s_prefill']:.0f} | {x['s_ttft']:.0f} | {x['ttft_gap']:.0f} | {x['c_tpot']:.1f} | {x['s_tpot']:.1f} | {x['c_e2e']:.0f} | {x['s_e2e']:.0f} | {x['e2e_gap']:.0f} |\n")
    print('md ->',md)
