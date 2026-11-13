from pathlib import Path
import json,shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from window_toy import compare
ROOT=Path(__file__).resolve().parents[1]
records=json.loads((ROOT/'results/exp23/formal-v2/replays.json').read_text())
plt.rcParams.update({'font.family':'Heiti TC','font.size':17,'axes.unicode_minus':False})
fig,axes=plt.subplots(2,1,figsize=(12,12.8),gridspec_kw={'height_ratios':[1.25,1]},facecolor='#f8f5ee')
fig.suptitle('exp23｜先验收，再算少做了什么',fontsize=28,y=.97)
ax=axes[0];ax.axis('off');ax.set_title('① 合成轨迹与成本：高置信，也会多做工作',loc='left',fontsize=23,pad=18)
scenarios=['all_correct_high','all_wrong_high','all_wrong_low','all_correct_low'];labels=['全对 · 高置信','全错 · 高置信','全错 · 低置信','全对 · 低置信']
data=[]
for scenario,label in zip(scenarios,labels):
 row=[]
 for policy in ['fixed5','candidate']:
  r=next(x for x in records if x['scenario']==scenario and x['length']==24 and x['cost']=='setup_heavy' and x['policy']==policy)
  row.append(str(r['work_points']))
 data.append([label]+row)
t=ax.table(cellText=data,colLabels=['教学场景','固定草稿5','合成置信度候选策略'],colWidths=[.36,.25,.39],loc='center',cellLoc='left');t.auto_set_font_size(False);t.set_fontsize(18);t.scale(1,3.2)
for (r,c),cell in t.get_celld().items():cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else '#fff')
ax.text(0,.02,'目标均为24个合成token；逐个目标基线均为21600工作点。\n每轮工作点 = 800 + 100 × 验证位置 + 25 × 草稿token。\n候选策略是累计合成置信度阈值0.8，不是DSpark源码调度。',transform=ax.transAxes,fontsize=16,color='#555')
ax=axes[1];ax.set_facecolor('#f8f5ee')
e=compare(list(range(1,17)),4,2,2,6)
ax.bar(['mask表示','compact表示','完整历史'],[e['mask'],e['compact'],e['full']],color=['#2f5f8a','#2f5f8a','#c38a30'],width=.55)
for i,v in enumerate([e['mask'],e['compact'],e['full']]):ax.text(i,v+3,str(v),ha='center',fontsize=22)
ax.set_ylim(0,220);ax.spines[['top','right']].set_visible(False)
ax.set_title('② 分层求和教学例：裁剪后相等，仍不同于完整历史',loc='left',fontsize=22,pad=20)
ax.set_ylabel('教学求和值；不是模型logits或质量分数')
ax.text(.5,-.18,'16个整数输入｜窗口4｜回看2步｜保留6个｜2层求和\n覆盖单层窗口与回看，未覆盖完整的跨层依赖。',transform=ax.transAxes,ha='center',va='top',fontsize=16,color='#555')
fig.text(.07,.025,'CPU合成教学实验：240条草稿重放＋99条窗口案例；例图另列并有单测。\n未执行DeepInfer或模型推理；工作点不是毫秒，不给真实速度/质量提升数字。',fontsize=16,color='#555')
fig.subplots_adjust(left=.16,right=.96,top=.88,bottom=.22,hspace=.5)
out=ROOT/'img/exp23.png';fig.savefig(out,dpi=160,facecolor=fig.get_facecolor());shutil.copyfile(out,ROOT.parent/'24-Phase5·5-少跑几圈/img/11-exp23.png')
(ROOT/'results/exp23/window-example.json').write_text(json.dumps({'scope':'separate toy illustration, not one of99 formal cases; covered by test_window.py','tokens':list(range(1,17)),**e},ensure_ascii=False,indent=2)+'\n');print(out)
