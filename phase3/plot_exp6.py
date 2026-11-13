#!/usr/bin/env python3
"""exp6：交互路 vs 批处理路，四种门。用法：../phase2/.venv/bin/python plot_exp6.py"""
import json,glob,os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
H=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(H,'results')
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Hiragino Sans GB.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED,BLUE,ORANGE,GREEN='#f8f5ee','#1c1a17','#6f695f','#2f5f8a','#c4763a','#4f7a52'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','text.color':INK,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
ARMS=[('exp6-pass','透传\n(vLLM FCFS)'),('exp6-fcfs','网关排队\nFCFS'),('exp6-prio','网关排队\n优先级'),('exp6-reserve','优先级\n+ 预留座位')]
runs={}
for f in glob.glob(os.path.join(R,'exp6-*.json')):
    d=json.load(open(f)); runs[d['name']]=d
arms=[(k,l) for k,l in ARMS if k in runs]; x=range(len(arms)); L=[l for _,l in arms]
I=[runs[k]['classes']['inter'] for k,_ in arms]; B=[runs[k]['classes']['batch'] for k,_ in arms]
def stall(k,c):  # 被卡过（任一字间 >100 ms）的请求占比，%
    f=glob.glob(os.path.join(R,f'{k}-*.req.jsonl'))[0]; rs=[r for r in map(json.loads,open(f)) if r['cls']==c and r.get('itl_ms')]
    return 100*sum(max(r['itl_ms'])>100 for r in rs)/len(rs)
fig,ax=plt.subplots(1,3,figsize=(17,5.4),dpi=160); fig.subplots_adjust(wspace=.3,left=.05,right=.98,top=.8,bottom=.18)
fig.suptitle('exp6 · 1 路交互（256/64，高优）+ 7 路批处理（2K/256）同车',x=.05,ha='left',fontsize=15,fontweight='bold')
fig.text(.05,.88,'进化之路 · P3·2 · Qwen3-1.7B · RTX 4060 8 GB · vLLM 0.8.5 · 网关预算 12,000',color=MUTED,fontsize=11)
w=.38
def bars(a,v1,v2,c1,c2,l1,l2,t,fmt='{:.0f}'):
    a.bar([i-w/2 for i in x],v1,w,color=c1,label=l1); a.bar([i+w/2 for i in x],v2,w,color=c2,label=l2)
    for i,(p,q) in enumerate(zip(v1,v2)):
        a.text(i-w/2,p,fmt.format(p),ha='center',va='bottom',fontsize=10); a.text(i+w/2,q,fmt.format(q),ha='center',va='bottom',fontsize=10)
    a.set_xticks(list(x)); a.set_xticklabels(L,fontsize=11); a.set_title(t,loc='left',fontweight='bold'); a.legend(frameon=False,fontsize=10); a.grid(axis='y',color='#eee8dc')
bars(ax[0],[c['ttft_p50']/1e3 for c in I],[c['ttft_p99']/1e3 for c in I],GREEN,'#a9c4aa','p50','p99','交互路 TTFT (s)','{:.2f}')
bars(ax[1],[stall(k,'inter') for k,_ in arms],[stall(k,'batch') for k,_ in arms],GREEN,ORANGE,'交互路','批处理路','被卡过的请求 %（任一字间 >100 ms）')
a=ax[2]; v=[c['out_tok_s'] for c in B]; a.bar(list(x),v,.6,color=BLUE)
for i,(q,c) in enumerate(zip(v,B)): a.text(i,q,f"{q:.0f} tok/s\nTTFT {c['ttft_p50']/1e3:.1f} s",ha='center',va='bottom',fontsize=10)
a.set_ylim(0,215); a.set_xticks(list(x)); a.set_xticklabels(L,fontsize=11); a.set_title('批处理路：输出吞吐与首字 p50',loc='left',fontweight='bold'); a.grid(axis='y',color='#eee8dc')
os.makedirs(os.path.join(H,'img'),exist_ok=True); out=os.path.join(H,'img','exp6.png'); fig.savefig(out); print(out)
