"""Export observed terminal/usage/tool boundaries from the formal native run."""
import argparse
import json
from pathlib import Path
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser=argparse.ArgumentParser();parser.add_argument('run',type=Path);args=parser.parse_args()
rows=json.loads((args.run/'records.json').read_text())['records']
def row(fixture,protocol='chat',mode='text'):
    return next(r for r in rows if r['fixture']['id']==fixture and r['protocol']==protocol and r['mode']==mode and r['pattern']=='whole')
plt.rcParams.update({'font.family':'Heiti TC','font.size':16,'axes.unicode_minus':False})
fig,axes=plt.subplots(3,1,figsize=(12,13),gridspec_kw={'height_ratios':[1,1,1.1]},facecolor='#f8f5ee')
fig.suptitle('exp20｜分块可以变，完成依据不能含糊',fontsize=25,y=.97)
def table(ax,title,headers,data,widths,font=15):
    ax.axis('off');ax.set_title(title,loc='left',fontsize=20,pad=18)
    t=ax.table(cellText=data,colLabels=headers,cellLoc='left',colLoc='left',loc='center',colWidths=widths)
    t.auto_set_font_size(False);t.set_fontsize(font);t.scale(1,3.0)
    for (r,c),cell in t.get_celld().items():
        cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else 'white')
data=[]
for f,label in [('plain_unicode','后端Finish(Stop)'),('missing_finish','缺Finish后调用finish()'),('client_close','本地调用close()')]:
    data.append([label]+[str(row(f,p)['semantic']['finish']) for p in ['chat','responses','messages']])
table(axes[0],'① 协议终态相似，结束来源仍须单列',['动作','Chat','Responses','Messages'],data,[.36,.18,.23,.23],14)
axes[0].text(0,-.04,'第二行没有收到后端Finish；第三行保留部分响应，未新增完成终态。',transform=axes[0].transAxes,fontsize=14,color='#555')
data=[]
for f,m,label in [('thinking_answer','text','Text，未提供计数'),('text_with_tokenizer','text_tokenizer','Text ＋ tokenizer'),('thinking_answer','tokens','Tokens ＋ tokenizer')]:
    u=row(f,mode=m)['response']['usage'];details=u.get('completion_tokens_details')
    data.append([label,str(u['completion_tokens']),str(details['reasoning_tokens']) if details else '缺项'])
table(axes[1],'② 同一段thinking→answer原文：Chat原始usage',['输入方式','completion总数','reasoning分项'],data,[.48,.25,.27],16)
axes[1].text(0,-.04,'Text总数只认chunk的token_count；附tokenizer可单独统计reasoning。\n0 / 缺项不自动等于“没有生成”；这些是合成后端输入，不是模型实测。',transform=axes[1].transAxes,fontsize=14,color='#555')
data=[]
for p,label in [('chat','Chat'),('responses','Responses'),('messages','Messages')]:
    r=row('unfinished_tool',p);a=r['semantic']['tools'][0]['arguments']
    data.append([label,r['semantic']['finish'],json.dumps(a,ensure_ascii=False) if isinstance(a,dict) else a])
table(axes[2],'③ 工具参数截断：终态没有替我们修补JSON',['协议','协议终态','最终参数字段'],data,[.22,.28,.5],16)
axes[2].text(0,-.03,'Messages累积器把解析失败的input回退为{}。原始参数增量仍是不完整JSON；\n“有tool_use”或“input是对象”均不足以批准执行工具。',transform=axes[2].transAxes,fontsize=14,color='#555')
fig.text(.05,.035,'recipe 0.2.0原生库，CPU；固定V4.1 tokenizer，合成后端输出。\n无模型推理、真实HTTP/浏览器网络、后端取消传播或工具执行结论。',fontsize=14,color='#555')
fig.subplots_adjust(left=.05,right=.96,top=.89,bottom=.15,hspace=.72)
out=Path(__file__).resolve().parents[1]/'img/exp20.png';out.parent.mkdir(exist_ok=True)
fig.savefig(out,dpi=160,facecolor=fig.get_facecolor())
target=out.parents[2]/'21-Phase5·2-广播分几段/img/11-exp20.png';shutil.copyfile(out,target)
print(out)
