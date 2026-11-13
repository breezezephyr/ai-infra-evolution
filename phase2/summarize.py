#!/usr/bin/env python3
"""把 phase2/results/*.json（vllm bench serve --save-result）汇成一张表。
用法：python3 summarize.py [results_dir] [--csv out.csv] [--prefix exp1]
列：name conc in out n  req/s  tok/s(out)  TTFT p50/p90/p99  TPOT p50/p90/p99  ITL p50/p99  E2E p50  prom_start prom_end env
"""
import json,glob,os,sys,csv
d=sys.argv[1] if len(sys.argv)>1 and not sys.argv[1].startswith('--') else os.path.join(os.path.dirname(__file__),'results')
args=sys.argv[2:] if d!=sys.argv[1:2] else sys.argv[1:]
pref=None; out=None
for i,a in enumerate(args):
    if a=='--prefix': pref=args[i+1]
    if a=='--csv': out=args[i+1]
rows=[]
for f in sorted(glob.glob(os.path.join(d,'*.json'))):
    r=json.load(open(f))
    name=r.get('name') or os.path.basename(f).rsplit('-',2)[0]
    if pref and not name.startswith(pref): continue
    g=lambda k: r.get(k)
    ms=lambda k: (g(k) or 0)
    rows.append(dict(name=name, conc=g('conc') or g('max_concurrency'), inp=round(r.get('total_input_tokens',0)/max(r.get('completed',1),1)),
        out=round(r.get('total_output_tokens',0)/max(r.get('completed',1),1)), n=g('completed'),
        rps=round(g('request_throughput') or 0,2), out_tps=round(g('output_throughput') or 0,1),
        ttft50=round(ms('median_ttft_ms')), ttft90=round(ms('p90_ttft_ms')), ttft99=round(ms('p99_ttft_ms')),
        tpot50=round(ms('median_tpot_ms'),2), tpot90=round(ms('p90_tpot_ms'),2), tpot99=round(ms('p99_tpot_ms'),2),
        itl50=round(ms('median_itl_ms'),2), itl99=round(ms('p99_itl_ms'),2), e2e50=round(ms('median_e2el_ms')),
        prom_start=g('prom_start'), prom_end=g('prom_end'), env=g('env')))
if not rows: sys.exit('no results')
cols=list(rows[0].keys())
w=[max(len(c),max(len(str(r[c])) for r in rows)) for c in cols]
print(' '.join(c.ljust(x) for c,x in zip(cols,w)))
for r in rows: print(' '.join(str(r[c]).ljust(x) for c,x in zip(cols,w)))
if out:
    with open(out,'w',newline='') as f: cw=csv.DictWriter(f,fieldnames=cols); cw.writeheader(); cw.writerows(rows)
    print('csv ->',out)
