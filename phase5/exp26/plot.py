"""Evidence matrix directly from accepted raw requests, not model performance claims."""
import json,pathlib,collections,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
ROOT=pathlib.Path(__file__).resolve().parents[2];R=ROOT/'phase5/results/exp26/formal-v1'
S=json.loads((R/'summary.json').read_text());assert S['accepted']
rows=[json.loads(x) for x in (R/'gateway.jsonl').read_text().splitlines()]
fontManager.addfont('/System/Library/Fonts/STHeiti Medium.ttc');plt.rcParams['font.family']=FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()
BG,INK,MUTED='#f8f5ee','#1c1a17','#6f695f'
fig=plt.figure(figsize=(12,12.8),dpi=160,facecolor=BG)
fig.text(.065,.957,'exp26 · 半路抛锚，三条线分别收尾',fontsize=23,weight='bold',color=INK)
fig.text(.065,.925,'12条受控场景 + 5条真实GPU场景 · 单卡顺序attempt · 故障均明确标记',fontsize=13,color=MUTED)
labels=['连接拒绝后重试','首段前超时后重试','首段后断流','审核拒绝','审核不可用','取消后迟到','旧generation失效','排空内完成','排空超时','排空时拒绝入口','无幂等key不重试','重复结算','GPU正常','GPU首段前故障重试','GPU首段后故障','GPU客户端断开','GPU排空超时']
terms={'completed':'完成','backend_error':'明确失败','review_rejected':'审核拒绝','review_unavailable':'审核不可用','cancelled':'取消','superseded':'已失效','drain_timeout':'排空超时','draining':'入口拒绝','client_disconnected':'客户端断开'}
fig.text(.065,.875,'场景',fontsize=14,weight='bold');fig.text(.41,.875,'终态',fontsize=14,weight='bold');fig.text(.61,.875,'attempt',fontsize=14,weight='bold');fig.text(.76,.875,'交付字节',fontsize=14,weight='bold')
y=.841
for i,(r,label) in enumerate(zip(rows,labels)):
 if i==12:
  y-=.025;fig.text(.065,y+.027,'真实Qwen3-0.6B / vLLM0.8.5，以下用量来自原生流',fontsize=12,color='#88702f');y-=.009
 col='#4f7a52' if r['terminal']=='completed' else '#b36c36'
 fig.text(.065,y,label,fontsize=12,color=INK);fig.text(.41,y,terms[r['terminal']],fontsize=12,color=col)
 fig.text(.64,y,str(len(r['attempts'])),fontsize=12,color=INK)
 fig.text(.79,y,str(len(r['sent_content'].encode())),fontsize=12,color=INK)
 fig.add_artist(plt.Line2D([.065,.925],[y-.01,y-.01],transform=fig.transFigure,color='#e6e0d4',lw=.7));y-=.032
native=[a for r in rows if r['mode']=='gpu' for a in r['attempts']];known=[a for a in native if a['usage'] is not None]
tokens=sum(a['usage']['total_tokens'] for a in known)
fig.text(.065,.225,'完成流含1条length截断；未验收答案质量。',fontsize=12,color=MUTED)
fig.text(.065,.19,f'GPU：{len(native)}次attempt，{len(known)}次有原生usage，共{tokens} token；{len(native)-len(known)}次未知。',fontsize=14,weight='bold')
fig.text(.065,.15,'未知保留为null；取消不等于0用量，合成计数不与GPU token求和。',fontsize=12,color=MUTED)
fig.text(.065,.11,'交付字节是网关send完成后的内容；客户端收到多少另核对原始SSE。',fontsize=12,color=MUTED)
fig.text(.065,.075,'同一物理后端，不代表HA；引擎请求清除不代表CUDA kernel级停机证明。',fontsize=12,color=MUTED)
out=ROOT/'27-Phase5·8-半路抛锚/img/11-exp26.png';out.parent.mkdir(exist_ok=True,parents=True);fig.savefig(out,dpi=160);plt.close(fig);print(out)
