"""Counts and native usage from one final run; no fabricated rates or model-call denominators."""
import json,pathlib,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
D=pathlib.Path(__file__).resolve().parent
S=json.loads((D.parent/'results/exp25/formal-v1/summary.json').read_text())
fontManager.addfont('/System/Library/Fonts/STHeiti Medium.ttc');plt.rcParams['font.family']=FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()
BG,INK,MUTED='#f8f5ee','#1c1a17','#6f695f'
plt.rcParams.update({'figure.facecolor':BG,'axes.facecolor':'white','text.color':INK,'axes.edgecolor':'#e6e0d4','font.size':13,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False})
fig=plt.figure(figsize=(12,12.8),dpi=160)
fig.text(.065,.958,'exp25 · 请求、attempt与token，分开对账',fontsize=22,weight='bold')
fig.text(.065,.925,'Qwen3-0.6B / vLLM 0.8.5 · 单个RTX4060 Laptop · 两个合成租户',fontsize=13,color=MUTED)
fig.text(.065,.885,'42条请求都有终态，包含预期拒绝；不是42个正确答案。',fontsize=15,weight='bold')
ax=fig.add_axes([.23,.585,.695,.255])
rows=[('已交付（含截断）','delivered','#4b7190'),('准入拒绝','admission_rejected','#b36c36'),('能力或参数拒绝','capability_rejected','#8a8378'),('规则审核拒绝','review_rejected','#b56262'),('身份拒绝','authentication_rejected','#a989a5'),('token预算拒绝','budget_rejected','#4f7a52')]
for i,(label,key,col) in enumerate(rows):
 n=S['terminal_counts'][key];y=5-i;ax.barh(y,n,height=.58,color=col);ax.text(n+.25,y,str(n),va='center',fontsize=13)
ax.set_yticks(range(5,-1,-1),[x[0] for x in rows]);ax.set_xlim(0,20);ax.set_xticks([0,5,10,15,20]);ax.set_xlabel('请求数 / 条',labelpad=10);ax.grid(axis='x',color='#eee8dc',zorder=0);ax.set_axisbelow(True)
fig.text(.065,.515,'17条交付 = 7次缓存命中 + 10次新生成后交付',fontsize=15,weight='bold')
fig.text(.065,.485,'12次生成attempt = 10次交付 + 2次规则拦截',fontsize=15,weight='bold')
fig.text(.065,.455,'交付中6条以length结束；单次生成用量保留，缓存不重复计生成。',fontsize=12,color=MUTED)
ax2=fig.add_axes([.16,.245,.765,.14])
for y,(tenant,label) in enumerate([('tenant-b','租户B'),('tenant-a','租户A')]):
 u=S['tenant_usage'][tenant];p=u['prompt_tokens'];o=u['completion_tokens']
 ax2.barh(y,p,color='#4b7190',height=.45,label='输入token' if y==0 else None)
 ax2.barh(y,o,left=p,color='#b36c36',height=.45,label='输出token' if y==0 else None)
 ax2.text(p/2,y,str(p),ha='center',va='center',color='white');ax2.text(p+o/2,y,str(o),ha='center',va='center',color='white')
 ax2.text(p+o+8,y,str(p+o),va='center')
ax2.set_yticks([0,1],['租户B','租户A']);ax2.set_xlim(0,450);ax2.set_xticks([0,100,200,300,400]);ax2.set_xlabel('后端原始usage归一化 / token',labelpad=10);ax2.legend(frameon=False,ncol=2,bbox_to_anchor=(0,1.3),loc='upper left');ax2.grid(axis='x',color='#eee8dc');ax2.set_axisbelow(True)
fig.text(.065,.18,'合计642 token；12 / 12 attempt可关联入口、SSE和原始usage。',fontsize=13,weight='bold')
fig.text(.065,.145,'2次规则拦截：模型正文交付0字节，已发生54 token仍留账。',fontsize=13,color='#88702f')
fig.text(.065,.095,'v1整段门控后发SSE；规则只识别LAB_BLOCK，不是通用安全审核。',fontsize=12,color=MUTED)
fig.text(.065,.068,'这是合成租户的token用量账；没有货币账单、GPU归属、容量或HA结论。',fontsize=12,color=MUTED)
out=D.parents[1]/'26-Phase5·7-把站台接起来/img/11-exp25.png';fig.savefig(out,dpi=160);plt.close(fig);print(out)
