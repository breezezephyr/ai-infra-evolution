from pathlib import Path
import json,shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'results/exp22/formal-v1/summary.json').read_text())
plt.rcParams.update({'font.family':'Heiti TC','font.size':16,'axes.unicode_minus':False})
fig,axes=plt.subplots(3,1,figsize=(12,14),gridspec_kw={'height_ratios':[1,1.5,1.1]},facecolor='#f8f5ee')
fig.suptitle('exp22｜同样输入，也要观察同车人',fontsize=28,y=.97)
ax=axes[0];ax.axis('off');ax.set_title('① 实际输出 token IDs：8个单独基线之后',loc='left',fontsize=22)
t=ax.table(cellText=[['正式请求','144 / 144 返回200'],['与单独基线比较','136 次'],['序列相同 / 不同','88 / 48'],['混合batch中的观察','85 条：37 相同 / 48 不同']],colWidths=[.48,.52],loc='center',cellLoc='left');t.auto_set_font_size(False);t.set_fontsize(18);t.scale(1,2.8)
for (r,c),cell in t.get_celld().items():cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#fff')
ax.text(0,-.15,'8题输入ID分别保持一致；贪心自由生成，未teacher forcing。\n48条差异与观测到的混批相关；本轮没有定位到具体数值kernel。',transform=ax.transAxes,fontsize=15,color='#555')
ax=axes[1];ax.set_facecolor('#f8f5ee');g=s['groups'];labels=[('直通' if r['mode']=='direct' else '准入2')+' · 并发'+str(r['concurrency']) for r in g]
vals=[r['batch_makespan_median_ms']/1000 for r in g]
ax.barh(range(6),vals,color=['#2f5f8a']*3+['#c38a30']*3)
for i,v in enumerate(vals):ax.text(v+.15,i,f'{v:.2f}s',va='center')
ax.set_yticks(range(6),labels);ax.invert_yaxis();ax.set_xlim(0,17);ax.spines[['top','right']].set_visible(False)
ax.set_title('② 每批8条请求全部完成：3轮耗时的中位数',loc='left',fontsize=22,pad=18);ax.set_xlabel('秒；闭环观察、生成轨迹不同，不能作等量算力或生产容量对比')
ax=axes[2];ax.axis('off');ax.set_title('③ 并发4：等待从一处挪到另一处',loc='left',fontsize=22)
rows=[]
for mode,label in [('direct','直通'),('bounded','准入2')]:
 r=next(x for x in g if x['mode']==mode and x['concurrency']==4)
 rows.append([label,f"{r['gateway_wait_ms']['median']/1000:.3f}s",f"{r['queue_ms']['median']/1000:.3f}s",f"{r['client_response_ms']['median']/1000:.2f}s"])
t=ax.table(cellText=rows,colLabels=['模式','网关等待','引擎首次排队','完整HTTP响应'],colWidths=[.18,.25,.28,.29],cellLoc='left',loc='center');t.auto_set_font_size(False);t.set_fontsize(16);t.scale(1,3)
for (r,c),cell in t.get_celld().items():cell.set_edgecolor('#ddd4c6');cell.set_facecolor('#f1e8ca' if r==0 else '#fff')
ax.text(0,-.04,'每模式24条，均为中位数；各列有不同的计时起止，不可直接相加。\n完整HTTP响应不是客户端TTFT；引擎首次排队不含所有decode步间等待。',transform=ax.transAxes,fontsize=15,color='#555')
fig.text(.07,.025,'RTX4060 Laptop / Qwen3-0.6B / vLLM0.8.5 V0 / BF16 / eager；32或96输出上限。\n有插桩开销；小样本、单卡、不评价答案质量；非DeepInfer运行或CUDA性能复现。',fontsize=15,color='#555')
fig.subplots_adjust(left=.23,right=.96,top=.90,bottom=.12,hspace=.55)
out=ROOT/'img/exp22.png';fig.savefig(out,dpi=160,facecolor=fig.get_facecolor());shutil.copyfile(out,ROOT.parent/'23-Phase5·4-班次表藏在哪里/img/11-exp22.png');print(out)
