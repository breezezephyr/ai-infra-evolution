"""Observed format and correctness stages, not a general model benchmark."""
import json,shutil
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'results/exp21/gpu-summary.json').read_text())
plt.rcParams.update({'font.family':'Heiti TC','font.size':16,'axes.unicode_minus':False})
fig,axes=plt.subplots(3,1,figsize=(12,12.8),gridspec_kw={'height_ratios':[1,1.15,1]},facecolor='#f8f5ee')
fig.suptitle('exp21｜格式受约束，答案仍要核对',fontsize=26,y=.97)
arms=['prompt_only','json_object','json_schema'];labels=['仅提示词','JSON语法约束','schema约束']
def table(ax,title,headers,data,widths):
 ax.axis('off');ax.set_title(title,loc='left',fontsize=21,pad=15)
 t=ax.table(cellText=data,colLabels=headers,cellLoc='left',colLoc='left',loc='center',colWidths=widths)
 t.auto_set_font_size(False);t.set_fontsize(16);t.scale(1,2.7)
 for (r,c),cell in t.get_celld().items():cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else '#fff')
table(axes[0],'① 每组分母均为40个计划请求',['组别','接收','JSON合法','schema合格','可交付'],[[label]+[s['arms'][arm][k] for k in ['accepted','json_valid','schema_valid','deliverable']] for arm,label in zip(arms,labels)],[.25,.14,.20,.22,.19])
axes[0].text(0,-.06,'schema组10条因数组长度关键字不支持而400拒绝；保留在40分母内。\n提示组33条以代码围栏开头，未自动剥离或修复；“可交付”须完整结束且答案正确。',transform=axes[0].transAxes,fontsize=14,color='#555')
ax=axes[1];y=[0,1,2];matched=s['matched_supported_subset']
ax.set_facecolor('#f8f5ee');ax.spines[['top','right']].set_visible(False)
ax.barh([v-.17 for v in y],[matched[a]['schema_valid'] for a in arms],height=.32,color='#2f5f8a',label='schema合格')
ax.barh([v+.17 for v in y],[matched[a]['deliverable'] for a in arms],height=.32,color='#c4763a',label='答案正确且完整')
for i,a in enumerate(arms):
 for off,k in [(-.17,'schema_valid'),(.17,'deliverable')]:ax.text(matched[a][k]+.3,i+off,str(matched[a][k]),va='center',fontsize=15)
ax.set_yticks(y,labels);ax.invert_yaxis();ax.set_xlim(0,38);ax.set_xlabel('同一组30个受支持任务配置｜三组都是30个分母')
ax.set_title('② 共同支持子集：结构通过不保证业务值正确',loc='left',fontsize=21,pad=15);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.27),ncol=2,frameon=False,fontsize=14)
table(axes[2],'③ schema约束接受的真实反例：不着急的查询',['字段','固定正确值','模型实际值'],[['kind','查询','查询'],['urgent','false','true']],[.25,.38,.37])
axes[2].text(0,-.05,'模型输出JSON可解析、字段齐全、类型合格；仍把“不着急”判成了紧急。\n本例未执行工具；schema允许boolean两值，没有包含业务答案。',transform=axes[2].transAxes,fontsize=14,color='#555')
fig.text(.05,.035,'RTX4060 Laptop / Qwen3-0.6B / vLLM0.8.5 / xgrammar0.1.18；20合成任务、2个seed。\n单并发，本轮有限样本；不代表通用正确率、生产SLO、DeepInfer实测或recipe端到端集成。',fontsize=14,color='#555')
fig.subplots_adjust(left=.23,right=.96,top=.89,bottom=.15,hspace=.75)
out=ROOT/'img/exp21.png';fig.savefig(out,dpi=160,facecolor=fig.get_facecolor());shutil.copyfile(out,ROOT.parent/'22-Phase5·3-按格式报站/img/11-exp21.png');print(out)
