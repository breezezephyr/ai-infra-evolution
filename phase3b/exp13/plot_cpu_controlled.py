#!/usr/bin/env python3
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2]
d=json.loads((ROOT/'phase3b/results/exp13-summary.json').read_text())
plt.rcParams['font.family']=['PingFang SC','Arial Unicode MS','sans-serif']
plt.rcParams['axes.unicode_minus']=False
fig,axes=plt.subplots(1,3,figsize=(14.5,4.9),facecolor='#f8f5ee')
labels=['透传','同步 73ms','异步 73ms','同步 297ms','异步 297ms']
rows=sorted([r for r in d['protocol'] if r['safe']],key=lambda r:(r['review_ms_replayed'],{'pass':0,'sync':1,'async':2}[r['mode']]))
bad=sorted([r for r in d['protocol'] if not r['safe']],key=lambda r:(r['review_ms_replayed'],{'pass':0,'sync':1,'async':2}[r['mode']]))
colors=['#9AA7B5','#4f7a52','#c4763a','#4f7a52','#c4763a']
a=axes[0];v=[r['first_visible_p50_ms'] for r in rows];a.bar(range(5),v,color=colors)
for i,y in enumerate(v):a.text(i,y+8,f'{y:.0f}',ha='center',fontsize=10)
a.set_xticks(range(5),labels,rotation=22,ha='right');a.set_ylim(0,530);a.set_ylabel('客户端首段正文 / ms');a.set_title('等成句，再等审核',pad=13)
a.text(.5,-.32,'受控HTTP回放；审核耗时取CPU实测中位数',transform=a.transAxes,ha='center',fontsize=9,color='#6f695f')
a=axes[1]
leak=[r['leaked_bad_chars_p50'] for r in bad];after=[r['after_bad_chars_p50'] for r in bad]
a.bar(range(5),leak,color=colors,label='标记句已下发的字符')
a.bar(range(5),after,bottom=leak,color='#d8c0a5',label='标记句之后仍下发的字符')
for i,(x,y) in enumerate(zip(leak,after)):a.text(i,x+y+1.2,f'{int(x)}+{int(y)}',ha='center',fontsize=9)
a.set_xticks(range(5),labels,rotation=22,ha='right');a.set_ylim(0,85);a.set_title('命中后截断，已发出的字收不回',pad=13);a.set_ylabel('Unicode 字符数')
a.legend(frameon=False,fontsize=8,loc='upper left')
a.text(.5,-.32,'门控测试使用已知标签；不是实际审核器的召回率',transform=a.transAxes,ha='center',fontsize=9,color='#6f695f')
a=axes[2];q=d['reviewer_quality'];x=range(3)
a.bar([i-.18 for i in x],[r['false_negatives'] for r in q],width=.36,color='#c4763a',label='6 条应拦里的漏判')
a.bar([i+.18 for i in x],[r['false_positives'] for r in q],width=.36,color='#2f5f8a',label='6 条允许里的误拦')
a.set_xticks(x,['嵌入 θ=.80','嵌入 θ=.90','0.6B 分类'],rotation=18,ha='right');a.set_ylim(0,6.5);a.set_title('判没判对，要另算一本账',pad=13);a.set_ylabel('条数 / 每类 6 条');a.legend(frameon=False,fontsize=8)
a.text(.5,-.32,'12 条手写样例；CPU；不是通用审核基准',transform=a.transAxes,ha='center',fontsize=9,color='#6f695f')
for a in axes:
 a.set_facecolor('#f8f5ee');a.spines[['top','right']].set_visible(False);a.grid(axis='y',alpha=.13)
fig.suptitle('exp13 · 审完再发与先发后审：放行机制、审核耗时、判定质量分开看',fontsize=14,y=.98)
fig.tight_layout(rect=[0,.12,1,.94],w_pad=2.3)
out=ROOT/'phase3b/img/exp13-cpu-controlled.png';fig.savefig(out,dpi=170,bbox_inches='tight',facecolor=fig.get_facecolor());print(out)
