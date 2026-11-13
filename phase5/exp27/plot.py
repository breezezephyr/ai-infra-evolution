"""Plot same-request intersection; all counts from one accepted run."""
import pathlib,json,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
ROOT=pathlib.Path(__file__).resolve().parents[2];S=json.loads((ROOT/'phase5/results/exp27/formal-v2/summary.json').read_text());assert S['accepted']
rows=S['requests'];eligible=[r for r in rows if r['eligible']]
fontManager.addfont('/System/Library/Fonts/STHeiti Medium.ttc');plt.rcParams['font.family']=FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()
BG,INK,MUTED='#f8f5ee','#1c1a17','#6f695f';plt.rcParams.update({'figure.facecolor':BG,'axes.facecolor':'white','text.color':INK,'axes.spines.top':False,'axes.spines.right':False,'font.size':13,'axes.edgecolor':'#e6e0d4'})
fig=plt.figure(figsize=(12,12.8),dpi=160);fig.text(.065,.958,'exp27 · 同一条请求，把条件一起验',fontsize=24,weight='bold')
fig.text(.065,.922,'formal-v2 · 42请求 / 37回答目标 · 固定小题 · 单GPU · 客户端同钟计时',fontsize=13,color=MUTED)
# Summary API names are deliberately mapped here, never inferred from HTTP status.
keys=[('protocol','协议有效含错误终态'),('quality','质量合格'),('slo','延迟门槛'),('joint','同条联合通过')]
ax=fig.add_axes([.23,.575,.69,.28]);colors=['#4b7190','#4f7a52','#b36c36','#88702f']
for i,((key,label),col) in enumerate(zip(keys,colors)):
 n=sum(r.get(key) is True for r in eligible);ax.barh(3-i,n,color=col,height=.55);ax.text(n+.4,3-i,str(n),va='center')
ax.set_yticks([3,2,1,0],[x[1] for x in keys]);ax.set_xlim(0,40);ax.set_xticks([0,10,20,30,37]);ax.set_xlabel('同一批回答目标请求 / 条');ax.grid(axis='x',color='#eee8dc');ax.set_axisbelow(True)
fig.text(.065,.515,'交集逐request计算；没有把不同实验的比率相乘。',fontsize=15,weight='bold')
fig.text(.065,.476,'完整流仍可能length截断；没有可评分回答单列unknown。',fontsize=13,color=MUTED)
fig.text(.065,.405,'正常直通 / 缓存冷 / 缓存暖：各6 / 6联合通过',fontsize=15,weight='bold')
fig.text(.065,.355,'算术对照：直通与集成各0 / 3质量合格',fontsize=15)
fig.text(.065,.30,'各层负载构成不同，不用总体比例比较两路优劣。',fontsize=12,color=MUTED)
u=S['metrics']['gpu'];fig.text(.065,.225,f'生成attempt {u["attempts"]}；已知usage {u["known_total_tokens"]} token；未知{u["unknown_usage_attempts"]}次。',fontsize=14,weight='bold')
fig.text(.065,.18,'首内容≤1000ms、完整结束≤3000ms；均为跑前冻结的实验门槛。',fontsize=12,color=MUTED)
fig.text(.065,.135,'应用缓存冷暖非GPU冷启动；进程占用区间非kernel秒。',fontsize=12,color=MUTED)
fig.text(.065,.09,'已知小计非完整消耗或货币账单；候选补丁本地验证、未提交。',fontsize=12,color=MUTED)
fig.savefig(ROOT/'28-Phase5·9-交班时拿什么说话/img/11-exp27.png',dpi=160);plt.close(fig)
