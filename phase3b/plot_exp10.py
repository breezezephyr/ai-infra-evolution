#!/usr/bin/env python3
import json,os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
H=os.path.dirname(os.path.abspath(__file__)); d=json.load(open(os.path.join(H,'results','exp10-summary.json')))
for fp in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Hiragino Sans GB.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family']=fm.FontProperties(fname=fp).get_name(); break
BG,INK,MUTED,GREEN,RED,ORANGE='#f8f5ee','#1c1a17','#6f695f','#4f7a52','#a84d3a','#c4763a'
plt.rcParams.update({'axes.facecolor':'#ffffff','figure.facecolor':BG,'axes.edgecolor':'#e6e0d4','text.color':INK,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False,'font.size':13})
ks=sorted(d,key=int); L=[f'期限 {k} s' for k in ks]; x=range(len(ks))
fig,ax=plt.subplots(1,2,figsize=(13,4.8),dpi=160); fig.subplots_adjust(wspace=.25,left=.06,right=.98,top=.8,bottom=.12)
fig.suptitle('exp10 · 停车：在途 6 条，等多久再断',x=.06,ha='left',fontsize=15,fontweight='bold')
fig.text(.06,.88,'进化之路 · P3b·1 · 输出 512 / 1024 / 1536 各 2 路 · 第 47 s 开始排空 · 最长一条 ≈ 1536 × 20 ms ≈ 31 s',color=MUTED,fontsize=11)
a=ax[0]; fin=[d[k]['finished'] for k in ks]; cut=[d[k]['cut'] for k in ks]
a.bar(x,fin,.55,color=GREEN,label='期限内跑完'); a.bar(x,cut,.55,bottom=fin,color=RED,label='被断')
a.set_xticks(list(x)); a.set_xticklabels(L); a.set_ylim(0,7.5); a.legend(frameon=False,fontsize=10,ncol=2,loc='upper left'); a.set_title('在途 6 条的去向',loc='left',fontweight='bold'); a.grid(axis='y',color='#eee8dc')
b=ax[1]; v=[d[k]['lost_tokens'] for k in ks]; b.bar(x,v,.55,color=ORANGE)
for i,vv in enumerate(v): b.text(i,vv,f'{vv:,}',ha='center',va='bottom',fontsize=11)
b.set_xticks(list(x)); b.set_xticklabels(L); b.set_title('白跑的字（生成后作废）',loc='left',fontweight='bold'); b.grid(axis='y',color='#eee8dc'); b.set_ylim(0,5200)
out=os.path.join(H,'img','exp10.png'); fig.savefig(out); print(out)
