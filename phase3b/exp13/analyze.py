#!/usr/bin/env python3
"""exp13：把审核质量、CPU测时、受控HTTP放行机制分开统计。"""
import json, statistics, hashlib
from pathlib import Path
from collections import defaultdict
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'phase3b/results'


def pct(values,q):
    s=sorted(values);p=(len(s)-1)*q;i=int(p);j=min(i+1,len(s)-1)
    return s[i]+(s[j]-s[i])*(p-i) if s else None


def reviewer_quality(data):
    gold={r['id']:r['blocked'] for r in data['cases']}
    metrics=[]
    # 阈值扫描只陈列这12条样例的结果，不在同一小样本宣称泛化精度。
    for name in ['embedding@0.80','embedding@0.90','classifier']:
        rows=data['classifier'] if name=='classifier' else data['embedding']
        # 质量按每case第一次测量评分；重复只是耗时测量，不扩大样本量。
        unique=[r for r in rows if r['repeat']==0]
        pred={r['id']:(r['verdict']=='BLOCK' if name=='classifier' else r['score']>=float(name.split('@')[1])) for r in unique}
        invalid=sum(r.get('verdict')=='INVALID' for r in unique)
        metrics.append({'reviewer':name,'n_cases':len(unique),'blocked_cases':sum(gold.values()),
                        'false_negatives':sum(gold[k] and not v for k,v in pred.items()),
                        'false_positives':sum(not gold[k] and v for k,v in pred.items()),
                        'invalid':invalid,'latency_n':len(rows),
                        'latency_p50_ms':pct([r['ms'] for r in rows],.5),
                        'latency_p90_ms':pct([r['ms'] for r in rows],.9)})
    return metrics


def main():
    original=json.loads((HERE/'reviewers-cpu.json').read_text())
    replay=json.loads((HERE/'http-replay.json').read_text())
    metrics=reviewer_quality(original)
    groups=defaultdict(list)
    for r in replay['records']:
        groups[(r['mode'],round(r['review_ms_replayed'],3),r['safe'])].append(r)
    protocol=[]
    for (mode,ms,safe),rows in groups.items():
        protocol.append({'mode':mode,'review_ms_replayed':ms,'safe':safe,'n':len(rows),
          'first_visible_p50_ms':pct([r['first_visible_ms'] for r in rows],.5),
          'max_gap_p50_ms':pct([r['max_visible_gap_ms'] for r in rows],.5),
          'leaked_bad_chars_p50':pct([r['leaked_bad_chars'] for r in rows],.5),
          'after_bad_chars_p50':pct([r['after_bad_chars'] for r in rows],.5),
          'max_burst_chars':max(r['max_burst_chars'] for r in rows),
          'finish_reasons':sorted({r['finish_reason'] for r in rows}),
          'source_closed':all(r['source']['closed'] for r in rows)})
    # 显式构造，名称只是样例。用相同定时负载作合法批处理/待核查样例对照。
    fixtures={
      'demo-scheduled-batch':{'label':'已授权定时批处理','times':[i*.5 for i in range(120)],'input':1024,'output':256},
      'demo-same-pattern-unknown':{'label':'用途未知；只凭节律不能判滥用','times':[i*.5 for i in range(120)],'input':1024,'output':256},
      'demo-long-context':{'label':'长上下文压力样例；是否违规取决于配额合同','times':[i*3 for i in range(20)],'input':8192,'output':64}}
    profiles=[]
    for key,d in fixtures.items():
        gaps=[b-a for a,b in zip(d['times'],d['times'][1:])]
        profiles.append({'key':key,'label':d['label'],'synthetic':True,'requests_60s':len(d['times']),
                         'interval_cv':statistics.pstdev(gaps)/statistics.mean(gaps),
                         'configured_input_tokens':d['input'],'configured_output_tokens':d['output'],
                         'reserved_token_total':len(d['times'])*(d['input']+d['output'])})
    result={'recorded_on':'2026-10-22','kind':'CPU_reviewer_measurements_plus_controlled_loopback_HTTP',
            'device':'cpu','latency_scope':original.get('latency_scope'),'http_smoke':replay.get('http_smoke',{}),'threads':original['threads'],'reviewer_quality':metrics,'protocol':protocol,
            'abuse_profiles':profiles,'inference':'No production abuse identified; no live generator GPU test',
            'sources':[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in [HERE/'cases.json',HERE/'reviewers-cpu.json',HERE/'http-replay.json']]}
    gpu_path=HERE/'reviewers-gpu.json'
    live_path=HERE/'gpu-live.json'
    if gpu_path.exists():
        gpu=json.loads(gpu_path.read_text())
        result['gpu']={'device':gpu['gpu_name'],'dtype':gpu['dtype'],'quality':reviewer_quality(gpu)}
        result['sources'].append({'path':str(gpu_path.relative_to(ROOT)),'sha256':hashlib.sha256(gpu_path.read_bytes()).hexdigest()})
    if live_path.exists():
        live=json.loads(live_path.read_text());live_groups=defaultdict(list)
        for row in live['records']:live_groups[(row['mode'],row['reviewer'],row['safe_input'])].append(row)
        result['live_gpu_protocol']=[]
        for (mode,reviewer,safe),rows in live_groups.items():
            med=lambda key: pct([r[key] for r in rows if r[key] is not None],.5) if any(r[key] is not None for r in rows) else None
            result['live_gpu_protocol'].append({'mode':mode,'reviewer':reviewer,'safe':safe,'n':len(rows),
              'first_visible_p50_ms':med('first_visible_ms'),'max_gap_p50_ms':med('max_visible_gap_ms'),
              'client_terminal_p50_ms':med('client_terminal_ms'),'visible_chars_p50':med('visible_chars'),
              'leaked_marked_chars_p50':med('leaked_marked_chars'),'after_marked_chars_p50':med('after_marked_chars'),
              'marked_sentence_observed':sum(r['marked_sentence_present_in_generated'] for r in rows),
              'correct_marked_window_block_count':sum(r['blocked_span_matches_marked'] for r in rows),
              'finish_reasons':sorted({r['finish_reason'] for r in rows}),
              'generated_tokens_p50':pct([r['source']['generated_new_tokens_including_eos'] for r in rows],.5),
              'generation_finish_reasons':sorted({r['source']['generation_finish_reason'] for r in rows}),
              'all_generator_threads_stopped':all(r['source']['thread_stopped'] for r in rows),
              'review_latency_p50_ms':pct([x['ms'] for r in rows for x in r['review_trace']],.5) if any(r['review_trace'] for r in rows) else None})
        result['kind']='CPU_and_GPU_review_measurements_controlled_replay_and_live_same_card_GPU'
        result['device']='mixed_cpu_and_cuda'
        result['primary_device']='cuda'
        result['inference']='live generator and reviewer share one GPU; no production abuse identified'
        result['live_gpu_model_config']={k:v for k,v in live.items() if k!='records'}
        result['sources'].append({'path':str(live_path.relative_to(ROOT)),'sha256':hashlib.sha256(live_path.read_bytes()).hexdigest()})
    OUT.mkdir(exist_ok=True)
    (OUT/'exp13-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('QUALITY',json.dumps(metrics,ensure_ascii=False))
    for r in protocol:print('CONTROLLED_GATE',json.dumps(r,ensure_ascii=False))
    if 'gpu' in result:print('GPU_QUALITY',json.dumps(result['gpu'],ensure_ascii=False))
    for r in result.get('live_gpu_protocol',[]):print('LIVE_GPU',json.dumps(r,ensure_ascii=False))

if __name__=='__main__':main()
