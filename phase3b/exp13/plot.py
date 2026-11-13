#!/usr/bin/env python3
"""GPU补跑主图；CPU及受控回放原图另存plot_cpu_controlled.py。"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2]
d=json.loads((ROOT/'phase3b/results/exp13-summary.json').read_text())
plt.rcParams['font.family']=['PingFang SC','Arial Unicode MS','sans-serif'];plt.rcParams['axes.unicode_minus']=False
fig,axes=plt.subplots(1,3,figsize=(14.5,5.1),facecolor='#f8f5ee')
a=axes[0]
cpu=[r['latency_p50_ms'] for r in d['reviewer_quality'] if r['reviewer']!='embedding@0.90']
gpu=[r['latency_p50_ms'] for r in d['gpu']['quality'] if r['reviewer']!='embedding@0.90']
a.bar([-.18,.82],cpu,width=.36,color='#9AA7B5',label='CPU FP32')
a.bar([.18,1.18],gpu,width=.36,color='#4f7a52',label='GPU BF16')
for i,(c,g) in enumerate(zip(cpu,gpu)):
 a.text(i-.18,c+6,f'{c:.0f}',ha='center',fontsize=10);a.text(i+.18,g+6,f'{g:.0f}',ha='center',fontsize=10)
a.set_xticks([0,1],['嵌入审核','0.6B 分类']);a.set_ylim(0,360);a.set_ylabel('独立审核 p50 / ms');a.set_title('审核单跑：GPU 明显更快',pad=13);a.legend(frameon=False,fontsize=9)
a.text(.5,-.31,'两种运行配置对照；不同精度，不是纯硬件加速比',transform=a.transAxes,ha='center',fontsize=8,color='#6f695f')
configs=[('pass','none'),('sync','embedding'),('async','embedding'),('sync','classifier'),('async','classifier')]
labels=['透传','同步嵌入','异步嵌入','同步分类','异步分类']
find=lambda safe,m,r:next(x for x in d['live_gpu_protocol'] if x['safe']==safe and x['mode']==m and x['reviewer']==r)
rows=[find(True,*c) for c in configs];bad=[find(False,*c) for c in configs]
colors=['#9AA7B5','#4f7a52','#c4763a','#4f7a52','#c4763a']
a=axes[1];v=[r['first_visible_p50_ms'] for r in rows]
a.bar(range(5),v,color=colors)
for i,y in enumerate(v):a.text(i,y+6,f'{y:.0f}',ha='center',fontsize=10)
a.set_xticks(range(5),labels,rotation=22,ha='right');a.set_ylim(0,max(v)*1.2);a.set_ylabel('安全流首段正文 p50 / ms');a.set_title('真实 GPU 生成 + 逐句真实审核',pad=13)
a.text(.5,-.31,'同卡三份0.6B权重；每种模式3轮，无延迟回放',transform=a.transAxes,ha='center',fontsize=8,color='#6f695f')
a=axes[2];leak=[r['leaked_marked_chars_p50'] for r in bad];after=[r['after_marked_chars_p50'] for r in bad]
a.bar(range(5),leak,color=colors,label='标记句已下发字符')
a.bar(range(5),after,bottom=leak,color='#d8c0a5',label='标记句后仍下发字符')
for i,(x,y) in enumerate(zip(leak,after)):
 suffix='\n漏判' if bad[i]['reviewer']=='classifier' else ''
 a.text(i,x+y+1.3,f'{int(x)}+{int(y)}'+suffix,ha='center',fontsize=9)
a.set_xticks(range(5),labels,rotation=22,ha='right');a.set_ylim(0,90);a.set_title('审核器漏判，同步也会放行',pad=13);a.set_ylabel('Unicode 字符数');a.legend(frameon=False,fontsize=8,loc='upper left')
a.text(.5,-.31,'按实际生成文本与拦截偏移对齐；无标记的样本另计',transform=a.transAxes,ha='center',fontsize=8,color='#6f695f')
for a in axes:
 a.set_facecolor('#f8f5ee');a.spines[['top','right']].set_visible(False);a.grid(axis='y',alpha=.13)
fig.suptitle('exp13 GPU补跑 · 快了多少、来不来得及、判没判对，要分开看',fontsize=14,y=.98)
fig.tight_layout(rect=[0,.12,1,.94],w_pad=2.3)
out=ROOT/'phase3b/img/exp13.png';fig.savefig(out,dpi=170,bbox_inches='tight',facecolor=fig.get_facecolor());print(out)
