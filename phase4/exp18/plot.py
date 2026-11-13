"""A standalone, exportable resource-accounting figure."""
import json
from pathlib import Path
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT/'results/exp18/resource-audit.json').read_text())
plt.rcParams.update({'font.family':'Heiti TC','font.size':17,'axes.unicode_minus':False})
fig, axes = plt.subplots(3,1,figsize=(12,13),gridspec_kw={'height_ratios':[1,1,1.2]})
fig.patch.set_facecolor('#f8f5ee')
for ax in axes:
    ax.set_facecolor('#f8f5ee')
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='x',alpha=.15)
    ax.set_axisbelow(True)
fig.suptitle('exp18｜同一批实验，三种账',fontsize=27,y=.98)

ax=axes[0]
values=[data['input_audio_minutes'],data['demo_turn_minutes'],data['formal_resident_window']['seconds']/60]
names=['输入音频（含插入静音）','36 次实验回合窗口之和','正式批次常驻窗口']
bars=ax.barh(names,values,color=['#2f5f8a','#c4763a','#E06C75'],height=.55)
for bar,value in zip(bars,values):
    ax.text(value+.04,bar.get_y()+bar.get_height()/2,f'{value:.3f}',va='center')
ax.invert_yaxis();ax.set_xlim(0,4.5);ax.set_xlabel('分钟｜真实用户会话分钟未测')
ax.set_title('① 时长先写分母；常驻窗口不含载入和热身',loc='left',pad=16)

ax=axes[1]
policies=['endpoint','eager','stable2']
p=[data['policies'][s] for s in policies]
volume=[s['cumulative_asr_audio_seconds']/60 for s in p]
bars=ax.barh(policies,volume,color=['#2f5f8a','#c4763a','#4f7a52'],height=.55)
for bar,value,s in zip(bars,volume,p):
    ax.text(value+.08,bar.get_y()+bar.get_height()/2,f'{value:.3f} 分钟 / {s["asr_calls"]} 次',va='center')
ax.invert_yaxis();ax.set_xlim(0,9)
ax.set_xlabel('累计提交给 ASR 的音频分钟\n每组原始输入均为 1.141 分钟',fontsize=16)
ax.set_title('② 重复前缀会重复提交；该时长不等于计算耗时或价格',loc='left',pad=16)

ax=axes[2]
selected=[s['selected_generation_tokens'] for s in p]
discarded=[s['discarded_tokens'] for s in p]
ax.barh(policies,selected,color='#2f5f8a',label='被选择的 generation')
ax.barh(policies,discarded,left=selected,color='#E06C75',label='未采用的 generation')
for i,(a,b) in enumerate(zip(selected,discarded)):
    ax.text(a/2,i,str(a),va='center',ha='center',color='white')
    if b:ax.text(a+b/2,i,str(b),va='center',ha='center',color='white')
    else:ax.text(a+15,i,'废弃 0',va='center')
ax.invert_yaxis();ax.set_xlim(0,1500);ax.set_xlabel('生成 token（含 EOS）｜被选择不代表语义质量已达标')
ax.set_title('③ 草稿提交前，先记重算和废弃量',loc='left',pad=16)
ax.legend(loc='lower right',frameon=False,fontsize=14)
idle=data['no_new_request_probe']
fig.text(.04,.016,f'补测 n=1：本实验无新请求 {idle["seconds"]:.2f}s，ASR+LLM 仍驻留；'
         f'全卡显存 {idle["resident_memory_mib"]["min"]} MiB（{idle["samples"]} 次采样）。\n'
         '图中不含实际账单、声学首声或并发容量；不同实验不能拼成生产 SLO。',fontsize=14,color='#555')
fig.subplots_adjust(left=.29,right=.96,top=.91,bottom=.12,hspace=.62)
out=ROOT/'img/exp18.png';out.parent.mkdir(exist_ok=True)
fig.savefig(out,dpi=160,facecolor=fig.get_facecolor())
dest=ROOT.parent/'19-Phase4·5-一分钟怎么算/img/11-exp18.png'
shutil.copyfile(out,dest)
print(out)
