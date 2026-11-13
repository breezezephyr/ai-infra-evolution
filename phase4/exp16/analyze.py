"""Recompute metrics from final raw events; fail instead of filling missing data."""
import argparse
import hashlib
import json
import statistics
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'results/exp16'


def load(path): return json.loads(Path(path).read_text())
def stats(values): return dict(n=len(values),p50=statistics.median(values),minimum=min(values),maximum=max(values))
def stamp(events, name): return next(e['monotonic_ns'] for e in events if e['event']==name)


def analyze():
    browser = load(DATA/'browser-formal-v1/records.json')
    assert len(browser['records']) == 18 and browser['failed_runs'] == 0 and not browser['errors']
    rows = []; history_examples = []; checks = []
    for client in browser['records']:
        run = client['run_id']; raw = load(DATA/f'server/final-v1/server-{run}.json')
        assert client['valid'] and client['outcome']=='complete' and not raw['errors'], run
        assert client['context_rate']==24000 and client['quantum_frames']==128
        assert client['trigger']['played']==client['trigger_samples']
        old = raw['generations']['1']; next_ = raw['generations']['2']
        stop = stamp(old['events'],'stop_signal_set'); joined = stamp(old['events'],'workers_joined')
        ordinary = [e for e in old['events'] if e['event']=='audio_sent']
        assert ordinary and not any(e['monotonic_ns']>stop for e in ordinary), run
        assert joined <= stamp(next_['events'],'generation_start'), run
        assert all(g['state']['llm_thread_stopped'] and g['state']['tts_thread_stopped'] and
                   g['state']['llm']['thread_stopped'] for g in [old,next_]), run
        for number,g in raw['generations'].items():
            with wave.open(str(DATA/f'server/final-v1/{run}-g{number}-sent.wav')) as f:
                assert (f.getframerate(),f.getnchannels(),f.getsampwidth())==(24000,1,2)
                pcm=f.readframes(f.getnframes())
            assert len(pcm)//2 == raw['sent'][number] == client['generations'][number]['received_samples']
            assert hashlib.sha256(pcm).hexdigest() == g['sent_pcm_sha256']
        assert raw['sent']['2']==raw['playback']['2']==next_['state']['computed_samples']==next_['state']['queued_samples']
        played = raw['playback']['1']
        retained = ''.join(p['text'] for p in old['segments'] if p['end']<=played)
        assert client['history'][0]['text']==retained and client['history'][0]['played']==played
        assistant = [m['content'] for m in next_['state']['llm']['prompt_messages'] if m['role']=='assistant']
        assert assistant == ([retained] if retained else []), run
        old_client = client['generations']['1']
        assert old_client['queued']==0 and old_client['played']==played
        assert old_client['accepted']==old_client['played']+old_client['discarded']
        recomputed = (old_client['last_render_end_frame']-client['trigger']['frame'])/24
        assert abs(recomputed-client['trigger_to_last_old_render_ms'])<1e-9
        if client['policy']=='full':
            assert client['stale_fence_rejection_count']==1
            assert client['flush_ack']['played']==played and old_client['invalid']
        else:
            assert played==raw['sent']['1'] and client['ignored_controlled_probe']==1
        row = dict(run_id=run,policy=client['policy'],trigger_ms=client['trigger_samples']/24,
            render_tail_ms=recomputed, played_after_trigger_samples=played-client['trigger_samples'],
            stop_to_join_ms=(joined-stop)/1e6,
            llm_finish=old['state']['llm']['finish_reason'],
            llm_model_return_after_stop_ms=(old['state']['llm']['generate_return_ns']-stop)/1e6,
            tts_discarded_after_stop_samples=old['state']['discarded_after_stop_samples'],
            sent=raw['sent']['1'],played=played,history_text=retained,
            discarded_client_samples=old_client['discarded'],
            notification_flush_ms=client['trigger_notification_to_flush_ack_notification_ms'])
        rows.append(row)
        if client['policy']=='full' and retained:
            history_examples.append(dict(run_id=run,played=played,generated_text=old['state']['text'],
                retained_text=retained,segments=old['segments'],next_prompt_messages=next_['state']['llm']['prompt_messages']))
        checks.append(dict(run_id=run,source_sha256_verified=True,no_ordinary_send_after_stop=True,
            workers_joined_before_next=True,history_used_by_next_model=True,next_samples_equal=True))
    groups=[]
    for policy in ['server_only','full']:
        for trigger in [200.,1000.,4000.]:
            group=[r for r in rows if r['policy']==policy and r['trigger_ms']==trigger]
            assert len(group)==3
            groups.append(dict(policy=policy,trigger_ms=trigger,
                render_tail_ms=stats([r['render_tail_ms'] for r in group]),
                stop_to_join_ms=stats([r['stop_to_join_ms'] for r in group])))
    probes=[]
    for record in load(DATA/'probes-formal-v1/records.json'):
        raw=load(DATA/'probes-formal-v1'/f"{record['run_id']}.json")
        events,state=raw['events'],raw['state']
        stop=stamp(events,'stop_signal_set')
        assert state['llm']['finish_reason']=='cancelled' and state['llm']['thread_stopped']
        assert state['llm_thread_stopped'] and state['tts_thread_stopped']
        before=max([e['tokens'] for e in state['llm']['token_steps'] if e['monotonic_ns']<=stop] or [0])
        probes.append(dict(run_id=raw['run_id'],kind=raw['kind'],
            stop_to_join_ms=(stamp(events,'workers_joined')-stop)/1e6,
            model_return_after_stop_ms=(state['llm']['generate_return_ns']-stop)/1e6,
            generated_tokens=state['llm']['generated_tokens'],tokens_since_last_pre_stop_check=state['llm']['generated_tokens']-before,
            tts_computed_samples=state['computed_samples'],tts_discarded_samples=state['discarded_after_stop_samples']))
    assert len(probes)==6
    probe_groups={kind:stats([r['stop_to_join_ms'] for r in probes if r['kind']==kind]) for kind in ['llm','tts']}
    environment=load(DATA/'server/final-v1/environment.json')
    for key,digest in environment['source_sha256'].items():
        assert hashlib.sha256((ROOT/key).read_bytes()).hexdigest()==digest,key
    resource=load(DATA/'server/final-v1/gpu-samples.json')
    summary=dict(schema='exp16.v1',date='2026-10-22',browser_version=browser['browser_version'],
        browser_runs=18,probe_runs=6,failed_browser_runs=0,groups=groups,rows=rows,
        probe_groups=probe_groups,probes=probes,history_examples=history_examples,
        full_history_nonempty=sum(bool(r['history_text']) for r in rows if r['policy']=='full'),
        full_stale_fence_rejections=9,normal_audio_sends_after_stop=0,next_generations_complete=18,
        gpu_full_card_observed_peak_mib=max(s['memory_mib'] for s in resource),
        gpu_resource_samples=len(resource),environment=environment,checks=checks,
        acoustic_stop_ms=None,microphone_onset_ms=None,vad_detection_ms=None,
        scope='actual CUDA LLM/TTS; synthetic playback-position interruption; SSH/WS; render is not acoustic output')
    summary['token_check_note']='StoppingCriteria is checked after token publication; the token-count difference is not proof of GPU tokens generated after stop.'
    target=ROOT/'results/exp16-summary.json'
    target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


def plot(summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'Heiti TC','axes.unicode_minus':False,'font.size':12,
                         'figure.facecolor':'#f8f5ee','axes.facecolor':'#ffffff'})
    fig,axes=plt.subplots(1,3,figsize=(16.8,5.6),gridspec_kw={'width_ratios':[1.15,1.15,1]})
    colors={'server_only':'#c4763a','full':'#4f7a52'}
    for ax,policy,title in zip(axes[:2],['server_only','full'],['只停服务端：旧音频渲染尾巴','清缓冲 + 旧版本屏障']):
        groups=[g for g in summary['groups'] if g['policy']==policy]
        for i,g in enumerate(groups):
            points=[r['render_tail_ms'] for r in summary['rows'] if r['policy']==policy and r['trigger_ms']==g['trigger_ms']]
            ax.scatter([i-.09,i,i+.09],points,c=colors[policy],s=52,zorder=3)
            ax.hlines(g['render_tail_ms']['p50'],i-.24,i+.24,color='#1c1a17',lw=2)
            ax.annotate(f"{g['render_tail_ms']['p50']:.1f}",(i,max(points)),xytext=(0,12),textcoords='offset points',ha='center',fontweight='bold')
        ax.set_xticks(range(3),['200','1000','4000']);ax.set_xlabel('触发时已播位置 / ms');ax.set_ylabel('触发 → 最后旧音频消费 / ms')
        ymax=max(g['render_tail_ms']['maximum'] for g in groups)
        ax.set_ylim(-.5 if policy=='full' else 0,max(12,ymax*1.3));ax.set_title(title,pad=20,fontweight='bold');ax.grid(axis='y',alpha=.18)
    ax=axes[2]
    for i,kind in enumerate(['llm','tts']):
        points=[r['stop_to_join_ms'] for r in summary['probes'] if r['kind']==kind]
        ax.scatter([i-.09,i,i+.09],points,color='#2f5f8a',s=52)
        median=statistics.median(points);ax.hlines(median,i-.24,i+.24,color='#1c1a17',lw=2)
        ax.annotate(f'p50 {median:.1f}',(i,median),xytext=(12,8),textcoords='offset points',ha='left',fontweight='bold')
    ax.set_xticks([0,1],['LLM 文字可用后','TTS 调用开始\n50 ms 后']);ax.set_ylabel('stop → 两工作线程 join / ms')
    ax.set_title('另六次 GPU 边界探针',pad=20,fontweight='bold');ax.set_ylim(0,max(r['stop_to_join_ms'] for r in summary['probes'])*1.4);ax.grid(axis='y',alpha=.18)
    for ax in axes:
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('exp16 · 播放停止与计算收尾，分别记账',fontsize=21,fontweight='bold',y=.98)
    fig.text(.04,.025,'每点一次，横线为 p50；每格 n=3。前两图纵轴不同。24 kHz / 128 帧 quantum。\n0 仅表示渲染块后无额外旧音频消费，非声学 0 ms。GPU 探针起点不同，不作模型速度排名。',fontsize=11,color='#6f695f')
    fig.subplots_adjust(left=.065,right=.98,bottom=.26,top=.79,wspace=.36)
    target=ROOT/'img/exp16.png';target.parent.mkdir(exist_ok=True);fig.savefig(target,dpi=200)
    plt.close(fig)


if __name__=='__main__':
    result=analyze();plot(result)
    print(json.dumps(dict(groups=result['groups'],probe_groups=result['probe_groups'],
        history_nonempty=result['full_history_nonempty'],gpu_peak=result['gpu_full_card_observed_peak_mib']),ensure_ascii=False,indent=2))
