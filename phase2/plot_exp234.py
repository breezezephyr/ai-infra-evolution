#!/usr/bin/env python3
"""exp2：TTFT / ITL vs 输入长度，预算 2048 与 8192 两条线。exp3 / exp4：成对柱状对比。
用法：.venv/bin/python plot_exp234.py exp2|exp3|exp4
"""
import json,glob,os,sys,re
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
which=sys.argv[1]; H=os.path.dirname(os.path.abspath(__file__)); d=os.path.join(H,'results'); os.makedirs(os.path.join(H,'img'),exist_ok=True)
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED,BLUE,ORANGE,GREEN='#f8f5ee','#1c1a17','#6f695f','#2f5f8a','#c4763a','#4f7a52'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','axes.labelcolor':INK,'xtick.color':MUTED,'ytick.color':MUTED,'text.color':INK,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
def load(pref):
    out=[]
    for f in sorted(glob.glob(os.path.join(d,f'{pref}*.json'))):
        r=json.load(open(f)); n=max(r.get('completed',1),1); name=r.get('name') or os.path.basename(f).rsplit('-',2)[0]
        out.append(dict(name=name,inp=round(r['total_input_tokens']/n),ttft50=r['median_ttft_ms'],ttft99=r['p99_ttft_ms'],itl50=r['median_itl_ms'],itl99=r['p99_itl_ms'],tpot50=r['median_tpot_ms'],tps=r['output_throughput'],e2e50=r['median_e2el_ms']))
    return out
def frame(title,n=3):
    fig,axes=plt.subplots(1,n,figsize=(5.4*n,5.2),dpi=160); fig.subplots_adjust(wspace=.32,left=.05,right=.98,top=.82,bottom=.16)
    fig.suptitle(title,x=.05,ha='left',fontsize=15,fontweight='bold',color=INK); fig.text(.05,.9,'进化之路 · P2 · Qwen3-1.7B · RTX 4060 8 GB · vLLM 0.8.5',color=MUTED,fontsize=11)
    return fig,(axes if n>1 else [axes])
if which=='exp2':
    rows=load('exp2'); groups={}
    for r in rows:
        bt=re.search(r'bt(\d+)',r['name']).group(1); groups.setdefault(bt,[]).append(r)
    fig,ax=frame('exp2 · 行李多重 × 每圈 token 预算')
    for bt,col in zip(sorted(groups,key=int),[ORANGE,BLUE]):
        g=sorted(groups[bt],key=lambda r:r['inp']); x=[r['inp'] for r in g]
        ax[0].plot(x,[r['ttft50'] for r in g],'o-',color=col,lw=2.5,label=f'预算 {bt}')
        ax[1].plot(x,[r['itl50'] for r in g],'o-',color=col,lw=2.5,label=f'p50 预算 {bt}'); ax[1].plot(x,[r['itl99'] for r in g],'o--',color=col,lw=1.5,alpha=.7,label=f'p99 预算 {bt}')
        ax[2].plot(x,[r['tps'] for r in g],'o-',color=col,lw=2.5,label=f'预算 {bt}')
    for a,t in zip(ax,['首字延迟 ms（p50）','每字间隔 ms','输出吞吐 tok/s']):
        a.set_title(t,loc='left',fontweight='bold'); a.set_xlabel('行李件数（输入 token）'); a.set_xscale('log',base=2); a.set_xticks(x); a.set_xticklabels([str(v) for v in x]); a.grid(axis='y',color='#eee8dc'); a.legend(frameon=False,fontsize=10)
    out=os.path.join(H,'img','exp2.png')
else:
    rows=load(which); pairs=[(r['name'],r) for r in rows]
    fig,ax=frame({'exp3':'exp3 · 常客寄存行李：开 / 关 prefix cache','exp4':'exp4 · 制造抢占：GPU_UTIL 0.90 → 0.70'}[which])
    names=[p[0].replace(which+'-','') for p in pairs]; xs=range(len(pairs))
    for a,(key,t) in zip(ax,[('ttft50','首字延迟 ms（p50）'),('itl50','每字间隔 ms（p50）'),('itl99','每字间隔 ms（p99）')]):
        a.bar(xs,[p[1][key] for p in pairs],color=[ORANGE if i%2==0 else BLUE for i in xs],width=.6)
        for i,p in enumerate(pairs): a.text(i,p[1][key],f'{p[1][key]:.0f}',ha='center',va='bottom',fontsize=11)
        a.set_xticks(list(xs)); a.set_xticklabels(names,fontsize=10); a.set_title(t,loc='left',fontweight='bold'); a.grid(axis='y',color='#eee8dc')
    out=os.path.join(H,'img',f'{which}.png')
fig.savefig(out); print('->',out)
for r in rows: print({k:(round(v,1) if isinstance(v,float) else v) for k,v in r.items()})
