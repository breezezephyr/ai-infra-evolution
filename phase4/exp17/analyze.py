"""Validate final raw measurements, then regenerate the summary and static plot."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'results/exp17'
sys.path.insert(0,str(Path(__file__).resolve().parent))
from revision import canonical


def load(path):return json.loads(Path(path).read_text())
def stats(values):return dict(n=len(values),p50=statistics.median(values),minimum=min(values),maximum=max(values))
def lcp(a,b):
    count=0
    for x,y in zip(a,b):
        if x!=y:break
        count+=1
    return count


def analyze():
    raw=load(DATA/'gpu-formal-v1/records.json')['records']
    environment=load(DATA/'gpu-formal-v1/environment.json')
    assert len(raw)==36
    assert environment['models']['asr']['device']=='cuda'
    assert environment['models']['llm']['device']=='cuda:0'
    for name,digest in environment['source_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    manifest={c['id']:c for c in load(ROOT/'exp14/audio/manifest.json')['cases']}
    cases=['short_03','pause_02','pause_03','long_02'];policies=['endpoint','eager','stable2']
    assert {(r['case_id'],r['policy'],r['repeat']) for r in raw}=={(c,p,i) for c in cases for p in policies for i in range(3)}
    rows=[];transcript_examples=[];checks=[]
    for r in raw:
        assert r['error'] is None,r['run_id']
        source=r['source'];events=r['events'];drafts=r['drafts'];case=manifest[r['case_id']]
        assert source['samples']==case['samples']
        audio=ROOT/'exp14/audio'/case['wav']
        assert hashlib.sha256(audio.read_bytes()).hexdigest()==case['sha256']==environment['inputs'][r['case_id']]['wav_sha256']
        assert source['pcm_sha256']==environment['inputs'][r['case_id']]['pcm_sha256']
        assert source['input_complete_ns']>=source['run_start_ns']+source['samples']*1e9/16000
        final=[c for c in r['asr_calls'] if c['final']]
        assert len(final)==1 and final[0]['offset']==source['samples']
        assert final[0]['started_ns']>=source['input_complete_ns']
        assert all(a['offset']<b['offset'] for a,b in zip(r['asr_calls'],r['asr_calls'][1:]))
        for call in r['asr_calls']:
            available=max(e['offset'] for e in events if e['event']=='input_frame_available' and e['monotonic_ns']<=call['started_ns'])
            assert call['offset']<=available
        selected=next(d for d in drafts if d['draft_id']==r['committed_draft'])
        assert selected['key']==r['final_key']==canonical(r['final_text'])
        assert selected['text_taken']==r['validated_text'] and r['validated_text']
        assert all(d['thread_stopped'] and d['state']['thread_stopped'] and not d['error'] for d in drafts)
        assert all(a['returned_ns']<=b['started_ns'] for a,b in zip(drafts,drafts[1:]))
        outputs=[e for e in events if e['event']=='validated_text_published']
        assert outputs and all(e['monotonic_ns']>=final[0]['ended_ns'] and e['draft_id']==selected['draft_id'] for e in outputs)
        assert ''.join(e['text'] for e in outputs)==r['validated_text']
        assert r['asr_cumulative_input_samples']==sum(c['offset'] for c in r['asr_calls'])
        assert r['wasted_generated_tokens']==sum(d['state']['generated_tokens'] for d in drafts if d['draft_id']!=selected['draft_id'])
        observations=[e for e in events if e['event']=='transcript_observed']
        changed=[e for e in observations if e['previous_key'] and e['key']!=e['previous_key']]
        retractions=[dict(offset=e['offset'],before=e['previous_key'],after=e['key'],
            retracted_chars=len(e['previous_key'])-lcp(e['previous_key'],e['key'])) for e in changed
            if not e['key'].startswith(e['previous_key'])]
        final_observation=next(e for e in observations if e['final'])
        row=dict(run_id=r['run_id'],case_id=r['case_id'],policy=r['policy'],repeat=r['repeat'],
            input_duration_ms=source['duration_ms'],validated_after_file_end_ms=r['first_validated_after_input_end_ms'],
            validated_after_final_asr_ms=(r['first_validated_text_ns']-final[0]['ended_ns'])/1e6,
            asr_calls=len(r['asr_calls']),asr_input_ratio=r['asr_cumulative_input_samples']/source['samples'],
            asr_call_wall_ms=r['asr_call_wall_ms'],asr_final_wall_ms=final[0]['wall_ms'],
            final_asr_wait_after_input_end_ms=(final[0]['started_ns']-source['input_complete_ns'])/1e6,
            draft_count=len(drafts),wasted_tokens=r['wasted_generated_tokens'],
            total_tokens=r['total_generated_tokens'],committed_tokens=selected['state']['generated_tokens'],
            reused_draft=selected['started_ns']<final_observation['monotonic_ns'],
            selected_started_before_file_end=r['committed_draft_started_before_input_end'],
            actual_rejected_pieces=r['rejected_piece_count'],normalized_text_retractions=len(retractions),
            normalized_text_changes=len(changed),final_text=r['final_text'],final_cer=r['final_cer'],
            running_invalidations=sum(e['was_running'] for e in events if e['event']=='draft_invalidated'),
            completed_invalidations=sum(not e['was_running'] for e in events if e['event']=='draft_invalidated'),
            asr_pending_replaced=r['asr_pending_replaced'],
            input_delivery_lateness_max_ms=max(source['source_delivery_lateness_ms']))
        rows.append(row)
        if r['policy']=='eager' and r['repeat']==0:
            transcript_examples.append(dict(run_id=r['run_id'],case_id=r['case_id'],
                observations=[dict(offset=e['offset'],audio_ms=e['offset']/16,text=e['text'],revision=e['revision'],final=e['final']) for e in observations],
                retractions=retractions,drafts=[dict(id=d['draft_id'],prompt=d['prompt'],finish=d['state']['finish_reason'],
                    tokens=d['state']['generated_tokens'],adopted=d['draft_id']==selected['draft_id']) for d in drafts]))
        checks.append(dict(run_id=r['run_id'],no_future_audio=True,no_text_before_final=True,
            committed_prompt_matches_final=True,only_selected_draft_published=True,workers_joined=True))
    groups=[]
    for case in cases:
        for policy in policies:
            entries=[r for r in rows if r['case_id']==case and r['policy']==policy]
            groups.append(dict(case_id=case,policy=policy,
                latency_ms=stats([r['validated_after_file_end_ms'] for r in entries]),
                after_final_asr_ms=stats([r['validated_after_final_asr_ms'] for r in entries]),
                final_asr_wall_ms=stats([r['asr_final_wall_ms'] for r in entries]),
                final_asr_wait_ms=stats([r['final_asr_wait_after_input_end_ms'] for r in entries]),
                asr_calls=stats([r['asr_calls'] for r in entries]),
                asr_input_ratio=stats([r['asr_input_ratio'] for r in entries]),
                wasted_tokens=stats([r['wasted_tokens'] for r in entries]),
                reused_count=sum(r['reused_draft'] for r in entries)))
    aggregates={}
    for policy in policies:
        entries=[r for r in rows if r['policy']==policy]
        aggregates[policy]=dict(n=len(entries),latency_ms=stats([r['validated_after_file_end_ms'] for r in entries]),
            asr_calls_total=sum(r['asr_calls'] for r in entries),drafts_total=sum(r['draft_count'] for r in entries),
            wasted_tokens_total=sum(r['wasted_tokens'] for r in entries),total_tokens=sum(r['total_tokens'] for r in entries),
            reused_count=sum(r['reused_draft'] for r in entries),
            actual_rejected_pieces=sum(r['actual_rejected_pieces'] for r in entries),
            running_invalidations=sum(r['running_invalidations'] for r in entries),
            completed_invalidations=sum(r['completed_invalidations'] for r in entries))
    queue=load(DATA/'frame-queue-v1/results.json');queue_rows=[]
    assert queue['synthetic_video_frames'] and not queue['real_video_inference']
    for r in queue['runs']:
        metrics=r['metrics'];completed=[f for f in r['frames'] if f['status']=='completed']
        dropped=[f for f in r['frames'] if f['status']=='dropped']
        assert len(r['frames'])==len(completed)+len(dropped)==300
        assert len(completed)==metrics['completed_count'] and len(dropped)==metrics['drop_count']
        assert metrics['final_pending_count']==0 and metrics['final_running_frame_id'] is None
        ages=sorted(f['finish_ticks']-f['capture_ticks'] for f in completed)
        assert ages[math.ceil(.95*len(ages))-1]/3==metrics['frame_age_completed']['p95_ms']
        assert all(f['start_ticks']>=f['capture_ticks'] and f['finish_ticks']-f['start_ticks']==f['service_ticks'] for f in completed)
        queue_rows.append(dict(policy=r['policy'],scenario=r['scenario'],completed=len(completed),dropped=len(dropped),
            drop_counts=metrics['drop_counts'],frame_age_p95_ms=metrics['frame_age_completed']['p95_ms'],
            drain_ms=metrics['drain_ticks']/3,highwater=metrics['pending_highwater']))
    resources=load(DATA/'gpu-formal-v1/gpu-samples.json')
    result=dict(schema='exp17.v1',date='2026-10-23',gpu_runs=36,failed_gpu_runs=0,warmup_runs=4,
        groups=groups,aggregates=aggregates,rows=rows,transcript_examples=transcript_examples,
        final_transcript_identical_by_case={case:len({r['final_text'] for r in rows if r['case_id']==case})==1 for case in cases},
        input_delivery_lateness_max_ms=max(r['input_delivery_lateness_max_ms'] for r in rows),
        queue=queue_rows,queue_scope='six deterministic virtual-clock runs; no video inference, not statistical repetitions',
        gpu_observed_full_card_peak_mib=max(r['memory_mib'] for r in resources),gpu_resource_samples=len(resources),
        environment=environment,checks=checks,acoustic_latency_ms=None,tts_audio=None,
        note='Latency begins at frozen-file supply completion, retaining about 800ms tail silence. Repeated cumulative prefix ASR is not native streaming. CER is literal normalized character distance, without simplified/traditional conversion.')
    (ROOT/'results/exp17-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def plot(s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'Heiti TC','axes.unicode_minus':False,'font.size':12,'figure.facecolor':'#f8f5ee','axes.facecolor':'white'})
    fig,axes=plt.subplots(2,2,figsize=(15,10.2));labels=['短句','停顿','追加要求','长请求']
    colors={'endpoint':'#2f5f8a','eager':'#c4763a','stable2':'#4f7a52'}
    names={'endpoint':'等文件结束','eager':'每变就起草','stable2':'两次相同门槛（提前0/12）'}
    for j,policy in enumerate(colors):
        groups=[g for g in s['groups'] if g['policy']==policy];x=np.arange(4)+(j-1)*.24
        med=np.array([g['latency_ms']['p50'] for g in groups])
        axes[0,0].bar(x,med,.22,label=names[policy],color=colors[policy],alpha=.9)
        axes[0,0].errorbar(x,med,yerr=[med-np.array([g['latency_ms']['minimum'] for g in groups]),np.array([g['latency_ms']['maximum'] for g in groups])-med],fmt='none',ecolor='#333333',capsize=3,lw=1)
        for a,b,g in zip(x,med,groups):axes[0,0].text(a,g['latency_ms']['maximum']+14,f'{b:.0f}',ha='center',fontsize=10)
    axes[0,0].set_title('文件供给结束 → 已验证文字就绪',pad=12);axes[0,0].set_ylabel('ms · p50，线段为最小–最大');axes[0,0].set_xticks(range(4),labels);axes[0,0].legend(fontsize=10,loc='upper left')
    axes[0,0].set_ylim(0,max(r['validated_after_file_end_ms'] for r in s['rows'])*1.18)
    for j,policy in enumerate(['endpoint','eager']):
        vals=[g['asr_input_ratio']['p50'] for g in s['groups'] if g['policy']==policy];x=np.arange(4)+(j-.5)*.32
        axes[0,1].bar(x,vals,.30,color=colors[policy],label='一次全量' if policy=='endpoint' else '前缀重识别（两策略相同）')
        for a,b in zip(x,vals):axes[0,1].text(a,b+.10,f'{b:.2f}×',ha='center',fontsize=11)
    axes[0,1].set_title('累计提交 ASR 的音频样本量',pad=12);axes[0,1].set_ylabel('累计输入样本 / 原文件样本');axes[0,1].set_xticks(range(4),labels);axes[0,1].set_ylim(0,8);axes[0,1].legend(fontsize=10)
    for j,policy in enumerate(['eager','stable2']):
        vals=[g['wasted_tokens']['p50'] for g in s['groups'] if g['policy']==policy];x=np.arange(4)+(j-.5)*.32
        axes[1,0].bar(x,vals,.30,color=colors[policy],label=names[policy])
        for a,b in zip(x,vals):axes[1,0].text(a,b+3,f'{b:.0f}',ha='center',fontsize=11)
    axes[1,0].set_title('最终未采用草稿的生成 token',pad=12);axes[1,0].set_ylabel('每条运行 · p50');axes[1,0].set_xticks(range(4),labels);axes[1,0].set_ylim(0,max(r['wasted_tokens'] for r in s['rows'])*1.25);axes[1,0].legend(fontsize=10)
    for j,scenario in enumerate(['fixed','burst']):
        vals=[r['frame_age_p95_ms'] for r in s['queue'] if r['scenario']==scenario];x=np.arange(3)+(j-.5)*.34
        axes[1,1].bar(x,vals,.32,color=['#778d9d','#b5676f'][j],label=['固定100ms','按源帧ID加入250ms慢服务'][j])
        for a,b in zip(x,vals):axes[1,1].text(a,b+65,f'{b:.0f}',ha='center',fontsize=10)
    axes[1,1].set_title('合成队列 · 完成帧的年龄 p95',pad=12);axes[1,1].set_xticks(range(3),['FIFO 30槽','只留最新','200ms采样\n+ 只留最新']);axes[1,1].set_ylabel('虚拟时钟 ms · 无视觉推理');axes[1,1].set_ylim(0,4900);axes[1,1].legend(fontsize=10,loc='upper right')
    for ax in axes.flat:ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('exp17 · 提前算可以，提前认定不行',fontsize=22,y=.985)
    fig.text(.055,.025,'GPU：4条冻结语音 × 3策略 × 3重复，每格 n=3。文件含约800ms尾静音，文字就绪不是首声；总时差不全归因于投机。\n队列：6组确定性虚拟时钟，各300合成帧；服务时长为人为设定，丢帧覆盖/视觉理解质量未测。',fontsize=11,color='#6f695f')
    fig.subplots_adjust(left=.075,right=.98,top=.92,bottom=.15,hspace=.38,wspace=.22)
    target=ROOT/'img/exp17.png';target.parent.mkdir(exist_ok=True);fig.savefig(target,dpi=200);plt.close(fig)


if __name__=='__main__':
    s=analyze();plot(s)
    print(json.dumps(dict(aggregates=s['aggregates'],identical_final=s['final_transcript_identical_by_case'],
        gpu_peak=s['gpu_observed_full_card_peak_mib'],queue=s['queue']),ensure_ascii=False,indent=2))
