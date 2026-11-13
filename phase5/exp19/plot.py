"""Standalone export figure: observed protocol differences, no performance claims."""
import json
from pathlib import Path
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'results/exp19/formal-v2/records.json').read_text())['records']
plt.rcParams.update({'font.family':'Heiti TC','font.size':16,'axes.unicode_minus':False})
fig=plt.figure(figsize=(12,12),facecolor='#f8f5ee')
grid=fig.add_gridspec(3,1,height_ratios=[1,1.05,1.05],hspace=.7)
axes=[fig.add_subplot(grid[i]) for i in range(3)]
fig.suptitle('exp19｜同样的请求意图，不同的转换规则',fontsize=26,y=.97)
for ax in axes:
    ax.set_facecolor('#f8f5ee');ax.spines[['top','right']].set_visible(False)
ax=axes[0];names=['Chat Completions','Responses','Messages']
accepted=[sum(r['protocol']==p and r['conversion']['status']=='ok' for r in rows) for p in ['chat','responses','messages']]
rejected=[sum(r['protocol']==p and r['conversion']['status']=='error' for r in rows) for p in ['chat','responses','messages']]
ax.barh(names,accepted,color='#2f5f8a',label='接受')
ax.barh(names,rejected,left=accepted,color='#c4763a',label='预期拒绝')
for i,(a,b) in enumerate(zip(accepted,rejected)):
    ax.text(a/2,i,str(a),ha='center',va='center',color='white')
    ax.text(a+b/2,i,str(b),ha='center',va='center',color='white')
ax.invert_yaxis();ax.set_xlim(0,18);ax.set_xlabel('预先冻结用例数｜每协议输入数与组成不同，不作能力排名')
ax.set_title('① 36条均完成合约检查；27条接受，9条预期拒绝',loc='left',pad=15)
ax.legend(loc='lower right',frameon=False,ncol=1,fontsize=13)

ax=axes[1];ax.axis('off')
ax.set_title('② 三条限额/停止串请求：prompt和token IDs相同',loc='left',pad=15)
table=ax.table(cellText=[['Chat','64','保留2项'],['Responses','64','忽略未知 stop'],['Messages','64','保留2项']],
    colLabels=['协议','转换后输出上限','转换后停止串'],cellLoc='left',colLoc='left',loc='center',colWidths=[.24,.27,.49])
table.auto_set_font_size(False);table.set_fontsize(17);table.scale(1,2.5)
for (r,c),cell in table.get_celld().items():
    cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else '#ffffff')
ax.text(0,-.12,'同prompt / 同token，不足以证明生成与解析设置相同。',transform=ax.transAxes,color='#555',fontsize=15)

ax=axes[2];ax.axis('off')
ax.set_title('③ 用户原文 a<｜User｜>：文本保留，控制身份不同',loc='left',pad=15)
table=ax.table(cellText=[['匹配prompt encoding','1','只把模板边界编码为User控制ID'],['直接对完整prompt分词','2','用户原文拼写也变成同一个控制ID']],
    colLabels=['编码方式','User控制ID次数','观测'],cellLoc='left',colLoc='left',loc='center',colWidths=[.34,.19,.47])
table.auto_set_font_size(False);table.set_fontsize(14);table.scale(1,3.0)
for (r,c),cell in table.get_celld().items():
    cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else '#ffffff')
fig.text(.04,.035,'真实recipe 0.2.0 native库，CPU；固定版本tokenizer。36个输入，非36种独立能力。\n'
         '不含模型推理、工具执行、服务吞吐或回答质量验证；图中接受/拒绝均是本库转换结果。',fontsize=14,color='#555')
fig.subplots_adjust(left=.24,right=.96,top=.89,bottom=.14)
out=ROOT/'img/exp19.png';out.parent.mkdir(exist_ok=True);fig.savefig(out,dpi=160,facecolor=fig.get_facecolor())
target=ROOT.parent/'20-Phase5·1-先验车票/img/11-exp19.png';target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out,target)
print(out)
