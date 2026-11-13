#!/usr/bin/env python3
"""exp8：启动分段堆叠条 + ITL 对比。用法：../phase2/.venv/bin/python plot_exp8.py"""
import json,os,collections,statistics as st,glob
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
H=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(H,'results')
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Hiragino Sans GB.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED='#f8f5ee','#1c1a17','#6f695f'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','text.color':INK,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
g=collections.defaultdict(list)
for l in open(os.path.join(R,'exp8-starts.jsonl')):
    d=json.loads(l); g[d['name'].rstrip('0123456789_')].append(d)
ARMS=[('nocompile','编译缓存丢了'),('pagecold','页缓存冷'),('warm','日常重启'),('graph','只捕获 6 个 graph'),('eager','eager')]
SEG=['进程+import','引擎进程+CUDA 初始化','读权重','torch.compile','profile+KV','CUDA graph','收尾']
COL=['#9a9386','#6f695f','#c4763a','#2f5f8a','#b8ad9b','#4f7a52','#ddd5c6']
fig,ax=plt.subplots(1,2,figsize=(16,5.6),dpi=160,gridspec_kw={'width_ratios':[2.2,1]}); fig.subplots_adjust(wspace=.28,left=.12,right=.98,top=.8,bottom=.12)
fig.suptitle('exp8 · 出一辆新车要多久：一次启动拆成七段',x=.04,ha='left',fontsize=15,fontweight='bold')
fig.text(.04,.88,'进化之路 · P3b·1 · Qwen3-1.7B 3.2 GiB · RTX 4060 8 GB · vLLM 0.8.5 · 每组 1–3 次均值',color=MUTED,fontsize=11)
a=ax[0]
for yi,(k,l) in enumerate(ARMS):
    left=0
    for s,c in zip(SEG,COL):
        vals=[x['seg'][s] for x in g[k] if x['seg'][s] is not None]
        v=st.mean(vals) if vals else 0
        if v: a.barh(yi,v,left=left,color=c,height=.62,label=s if yi==2 else None)
        if v>=3: a.text(left+v/2,yi,f'{v:.0f}',ha='center',va='center',color='#fff',fontsize=10)
        left+=v
    a.text(left+1,yi,f'{left:.1f} s',va='center',fontsize=12,fontweight='bold')
a.set_yticks(range(len(ARMS))); a.set_yticklabels([l for _,l in ARMS]); a.invert_yaxis(); a.set_xlim(0,100); a.set_xlabel('秒'); a.grid(axis='x',color='#eee8dc')
a.legend(frameon=False,fontsize=10,ncol=4,loc='lower right',bbox_to_anchor=(1,.02)); a.set_title('分段（秒）',loc='left',fontweight='bold')
b=ax[1]; conc=[1,8,16]; x=range(3); w=.26
for i,(k,l,c) in enumerate([('warm','默认 67 尺寸','#2f5f8a'),('graph6','6 尺寸','#4f7a52'),('eager','eager','#c4763a')]):
    v=[json.load(open(glob.glob(os.path.join(R,f'exp8-{k}-c{n}-*.json'))[0]))['median_itl_ms'] for n in conc]
    b.bar([j+(i-1)*w for j in x],v,w,color=c,label=l)
    for j,vv in enumerate(v): b.text(j+(i-1)*w,vv,f'{vv:.1f}',ha='center',va='bottom',fontsize=9)
b.set_xticks(list(x)); b.set_xticklabels([f'并发 {n}' for n in conc]); b.set_ylim(0,27); b.set_title('省下的启动时间，每字付多少：ITL p50 (ms)',loc='left',fontweight='bold',fontsize=12); b.legend(frameon=False,fontsize=10,loc='upper left',ncol=3); b.grid(axis='y',color='#eee8dc')
out=os.path.join(H,'img','exp8.png'); fig.savefig(out); print(out)
