"""Scientific figure from final-v2 raw-derived summary; min/max, never inferred p99."""
import json,pathlib,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
D=pathlib.Path(__file__).resolve().parent
R=D.parent/'results/exp24/formal-v3'
S=json.loads((R/'summary.json').read_text())
FONT='/System/Library/Fonts/STHeiti Medium.ttc'
fontManager.addfont(FONT);plt.rcParams['font.family']=FontProperties(fname=FONT).get_name()
BG,INK,MUTED='#f8f5ee','#1c1a17','#6f695f'
plt.rcParams.update({'figure.facecolor':BG,'axes.facecolor':'white','text.color':INK,'axes.edgecolor':'#e6e0d4','font.size':13,'xtick.color':MUTED,'ytick.color':MUTED,'axes.spines.top':False,'axes.spines.right':False})
fig=plt.figure(figsize=(12,12.8),dpi=160)
fig.text(.065,.958,'exp24 · 取回字节，再判断能否复用',fontsize=22,weight='bold')
fig.text(.065,.925,'Mooncake non-CUDA 0.3.13.post1 · DARYU · 单机跨进程 / TCP配置',fontsize=13,color=MUTED)
fig.text(.065,.895,'40 / 40 对象：长度、SHA256一致；238次API操作与12个身份案例分列',fontsize=14,weight='bold')
ax=fig.add_axes([.135,.565,.79,.27])
labels=['1B','4KiB','64KiB','1MiB'];colors={'put':'#b36c36','get':'#4b7190','remove':'#4f7a52'}
for op,offset in [('put',-.2),('get',0),('remove',.2)]:
 rows=sorted((x for x in S['timings'] if x['op']==op),key=lambda x:x['size_bytes'])
 for i,r in enumerate(rows):
  y=3-i+offset;med=r['median_ms']
  ax.plot([r['min_ms'],r['max_ms']],[y,y],color=colors[op],lw=2,alpha=.5)
  ax.scatter([med],[y],color=colors[op],s=42,label=op if i==0 else None,zorder=3)
ax.set_yticks([3,2,1,0],labels);ax.set_xscale('log');ax.set_xlim(.045,1.8)
ax.set_xticks([.05,.1,.2,.5,1],['0.05','0.1','0.2','0.5','1.0'])
ax.set_xlabel('Python Store调用时延 / ms（点：中位数；线：最小～最大）',fontsize=12,labelpad=12)
ax.grid(axis='x',color='#eee8dc');ax.legend(frameon=False,ncol=3,loc='upper left',bbox_to_anchor=(0,1.16),fontsize=12)
fig.text(.065,.493,'每档每种操作n=10，串行、未预热；put生成字节在计时前，hash在计时后。',fontsize=12,color=MUTED)
fig.text(.065,.469,'不是纯网络时间、生产尾延迟、RDMA带宽或P/D性能。',fontsize=12,color=MUTED)
# Event evidence is a table, using raw-observed semantics rather than success totals.
ax2=fig.add_axes([.065,.2,.87,.245]);ax2.axis('off')
rows=[['重复put：同值 / 异值 / 异长度','均返回0；读回均是最初4KiB'],
 ['不存在的键','get为空字节；is_exist为0'],
 ['master停止','get为空字节；is_exist / put为−900'],
 ['master重启，保留原client','约3秒后、再等12秒：原键查不到'],
 ['新client与恢复探针','原键查不到；新键写 / 读 / 删成功']]
t=ax2.table(cellText=rows,colWidths=[.43,.57],cellLoc='left',bbox=[0,0,1,1]);t.auto_set_font_size(False);t.set_fontsize(12)
for (i,j),cell in t.get_celld().items():
 cell.set_edgecolor('#e6e0d4');cell.set_facecolor('white' if i%2==0 else '#f1eee5');cell.PAD=.055
fig.text(.065,.155,'重启观察：无HA、快照恢复、SSD；不等于所有配置都不保留数据。',fontsize=12,color=MUTED)
fig.text(.065,.128,'读取方B不贡献存储段，40个对象由A写入；不是同进程读回。',fontsize=12,color=MUTED)
fig.text(.065,.08,'内容一致 ≠ 模型KV可导入；身份合约仍需真实连接层与模型验证。',fontsize=14,weight='bold',color='#88702f')
out=D.parents[1]/'25-Phase5·6-行李不跟车走/img/11-exp24.png';fig.savefig(out,dpi=160);plt.close(fig)
print(out)
