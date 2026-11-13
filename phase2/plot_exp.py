#!/usr/bin/env python3
"""把 results/ 里某个实验的 JSON 画成系列图卡风格的曲线图（米色底、蓝橙绿）。
用法：python3 plot_exp.py exp1 [--x conc|inp] [--out img/exp1.png]
"""
import json,glob,os,sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
pref=sys.argv[1]; args=sys.argv[2:]
xkey='conc'; out=None
for i,a in enumerate(args):
    if a=='--x': xkey=args[i+1]
    if a=='--out': out=args[i+1]
d=os.path.join(os.path.dirname(os.path.abspath(__file__)),'results')
rows=[]
for f in sorted(glob.glob(os.path.join(d,f'{pref}*.json'))):
    r=json.load(open(f)); n=max(r.get('completed',1),1)
    rows.append(dict(conc=int(r.get('conc') or r.get('max_concurrency')), inp=round(r['total_input_tokens']/n),
        out_tps=r['output_throughput'], rps=r['request_throughput'], ttft50=r['median_ttft_ms'], ttft99=r['p99_ttft_ms'],
        tpot50=r['median_tpot_ms'], tpot99=r['p99_tpot_ms'], itl50=r['median_itl_ms'], itl99=r['p99_itl_ms'], e2e50=r['median_e2el_ms']))
rows.sort(key=lambda r:r[xkey])
if not rows: sys.exit('no results for '+pref)
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED,BLUE,ORANGE,GREEN='#f8f5ee','#1c1a17','#6f695f','#2f5f8a','#c4763a','#4f7a52'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','axes.labelcolor':INK,'xtick.color':MUTED,'ytick.color':MUTED,'text.color':INK,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
x=[r[xkey] for r in rows]; xl={'conc':'车上坐几人（并发）','inp':'行李件数（输入 token）'}[xkey]
fig,axes=plt.subplots(1,3,figsize=(16,5.2),dpi=160); fig.subplots_adjust(wspace=.32,left=.05,right=.98,top=.82,bottom=.16)
ax=axes[0]; ax.plot(x,[r['itl50'] for r in rows],'o-',color=BLUE,lw=2.5,label='ITL p50'); ax.plot(x,[r['itl99'] for r in rows],'o--',color=ORANGE,lw=2,label='ITL p99'); ax.set_title('每字间隔 ms',loc='left',fontweight='bold'); ax.set_xlabel(xl); ax.legend(frameon=False)
ax=axes[1]; ax.plot(x,[r['out_tps'] for r in rows],'o-',color=GREEN,lw=2.5); ax.set_title('输出吞吐 tok/s',loc='left',fontweight='bold'); ax.set_xlabel(xl)
ax=axes[2]; ax.plot(x,[r['ttft50'] for r in rows],'o-',color=BLUE,lw=2.5,label='TTFT p50'); ax.plot(x,[r['ttft99'] for r in rows],'o--',color=ORANGE,lw=2,label='TTFT p99'); ax.set_title('首字延迟 ms',loc='left',fontweight='bold'); ax.set_xlabel(xl); ax.legend(frameon=False)
for ax in axes:
    ax.grid(axis='y',color='#eee8dc'); ax.set_xscale('log',base=2) if xkey=='conc' else None; ax.set_xticks(x); ax.set_xticklabels([str(v) for v in x])
fig.suptitle(f'{pref} · Qwen3-1.7B · RTX 4060 8 GB · vLLM 0.8.5',x=.05,ha='left',fontsize=15,fontweight='bold',color=INK)
fig.text(.05,.9,'进化之路 · P2',color=MUTED,fontsize=11)
out=out or os.path.join(os.path.dirname(os.path.abspath(__file__)),'img',f'{pref}.png'); os.makedirs(os.path.dirname(out),exist_ok=True)
fig.savefig(out); print('->',out)
for r in rows: print(r)
