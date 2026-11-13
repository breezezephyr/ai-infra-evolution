#!/usr/bin/env python3
"""exp7：两辆车，四种选车法。用法：../phase2/.venv/bin/python plot_exp7.py"""
import json,glob,os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
H=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(H,'results')
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Hiragino Sans GB.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED,BLUE,ORANGE,GREEN='#f8f5ee','#1c1a17','#6f695f','#2f5f8a','#c4763a','#4f7a52'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','text.color':INK,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
ARMS=[('exp7-rr','轮询\n常客均匀'),('exp7-hash','前缀哈希\n常客均匀'),('exp7-hash-zipf','前缀哈希\n常客倾斜'),('exp7-bounded','有界哈希\n常客倾斜')]
runs={}
for f in glob.glob(os.path.join(R,'exp7-*.json')):
    d=json.load(open(f)); runs[d['name']]=d
arms=[(k,l) for k,l in ARMS if k in runs]; x=list(range(len(arms))); L=[l for _,l in arms]; w=.38
S=[runs[k]['servers'] for k,_ in arms]; U=[runs[k]['classes']['user'] for k,_ in arms]
fig,ax=plt.subplots(1,3,figsize=(17,5.4),dpi=160); fig.subplots_adjust(wspace=.3,left=.05,right=.98,top=.8,bottom=.22)
fig.suptitle('exp7 · 两辆车，8 组常客（1.5K 公共前缀），怎么选车',x=.05,ha='left',fontsize=15,fontweight='bold')
fig.text(.05,.88,'进化之路 · P3·3 · Qwen3-0.6B × 2 · RTX 4060 8 GB · 每辆 KV 9,952 token · 并发 8',color=MUTED,fontsize=11)
def pair(a,v1,v2,t,fmt,l=('车 A :8004','车 B :8005')):
    a.bar([i-w/2 for i in x],v1,w,color=BLUE,label=l[0]); a.bar([i+w/2 for i in x],v2,w,color=ORANGE,label=l[1])
    for i,(p,q) in enumerate(zip(v1,v2)):
        a.text(i-w/2,p,fmt.format(p),ha='center',va='bottom',fontsize=10); a.text(i+w/2,q,fmt.format(q),ha='center',va='bottom',fontsize=10)
    a.set_xticks(x); a.set_xticklabels(L,fontsize=11); a.set_title(t,loc='left',fontweight='bold'); a.legend(frameon=False,fontsize=10); a.grid(axis='y',color='#eee8dc')
pair(ax[0],[100*s['8004']['hit_rate'] for s in S],[100*s['8005']['hit_rate'] for s in S],'寄存箱命中率 %（按 block，上限 96）','{:.0f}'); ax[0].set_ylim(0,105)
pair(ax[1],[s['8004']['done'] for s in S],[s['8005']['done'] for s in S],'每辆车完成条数（负载分布）','{:.0f}')
pair(ax[2],[u['ttft_p90'] for u in U],[u['itl_p99'] for u in U],'没命中的代价 (ms)','{:.0f}',('TTFT p90','ITL p99'))
ax[2].set_xticklabels([f"{l}\n{u['out_tok_s']:.0f} tok/s" for l,u in zip(L,U)],fontsize=11)
out=os.path.join(H,'img','exp7.png'); fig.savefig(out); print(out)
