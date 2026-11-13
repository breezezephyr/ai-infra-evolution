"""Offline ledgers. Time units and denominators are explicit; missing != zero."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import wave


def union_ns(intervals):
    end = None
    total = 0
    for start, stop in sorted(intervals):
        if stop < start:
            raise ValueError('negative interval')
        if end is None or start > end:
            total += stop - start
        else:
            total += max(0, stop - end)
        end = max(end, stop) if end is not None else stop
    return total


def distribution(values):
    data = sorted(v for v in values if v is not None)
    def quantile(q):
        if not data:
            return None
        index = (len(data) - 1) * q
        lo, hi = math.floor(index), math.ceil(index)
        return data[lo] + (data[hi] - data[lo]) * (index - lo)
    return dict(eligible=len(values), measured=len(data), unknown=len(values)-len(data),
                p50=quantile(.5), p95=quantile(.95),
                min=min(data) if data else None, max=max(data) if data else None)


def assumed_cost(resident_seconds, session_minutes, rate_per_gpu_hour):
    if resident_seconds < 0 or rate_per_gpu_hour < 0:
        raise ValueError('negative price or duration')
    if session_minutes is not None and session_minutes <= 0:
        raise ValueError('nonpositive denominator')
    numerator = resident_seconds / 3600 * rate_per_gpu_hour
    return dict(assumed_rate_per_gpu_hour=rate_per_gpu_hour,
                assumed_gpu_cost=numerator,
                cost_per_session_minute=numerator / session_minutes if session_minutes is not None else None,
                actual_bill=None, other_costs=None)


def source_ref(path, root):
    return dict(path=str(path.relative_to(root)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def frozen_cases(root):
    manifest = json.loads((root / 'exp14/audio/manifest.json').read_text())
    result = {}
    for case in manifest['cases']:
        if case['id'] not in {'short_03', 'pause_02', 'pause_03', 'long_02'}:
            continue
        path = root / 'exp14/audio' / case['wav']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == case['sha256']
        with wave.open(str(path)) as wav:
            assert wav.getframerate() == case['sample_rate'] == 16000
            assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
            pcm = wav.readframes(wav.getnframes())
        assert len(pcm) // 2 == case['samples']
        pauses = [(p['start'], p['end']) for p in case['inserted_pauses']]
        tail = (case['samples'] - case['tail_silence_samples'], case['samples'])
        for start, end in pauses + [tail]:
            assert not any(pcm[start * 2:end * 2]), 'annotated silence is not all-zero PCM'
        result[case['id']] = dict(samples=case['samples'], sample_rate=16000,
            pcm_sha256=hashlib.sha256(pcm).hexdigest(),
            inserted_pause_samples=union_ns(pauses), tail_silence_samples=tail[1]-tail[0],
            source=source_ref(path, root))
    return result


def resource_ledger(records, cases):
    ids = [r['run_id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate run ID')
    rows = []
    for record in records:
        source = record['source']
        if source['clock'] != 'server_monotonic':
            raise ValueError('clock mismatch')
        events = record['events']
        if any(e['clock_domain'] != 'server_monotonic' for e in events):
            raise ValueError('clock mismatch')
        end = [e['monotonic_ns'] for e in events if e['event'] == 'all_workers_joined']
        if len(end) != 1:
            raise ValueError('missing/ambiguous joined boundary')
        case = cases[record['case_id']]
        assert source['pcm_sha256'] == case['pcm_sha256']
        assert source['samples'] == case['samples']
        start = source['run_start_ns']
        if end[0] < start or record['error'] is not None:
            raise ValueError('failed/negative formal record')
        drafts = record['drafts']
        if not all(d['thread_stopped'] and d['state']['thread_stopped'] for d in drafts):
            raise ValueError('worker still running')
        total_tokens = sum(d['state']['generated_tokens'] for d in drafts)
        wasted = sum(d['state']['generated_tokens'] for d in drafts if d['draft_id'] != record['committed_draft'])
        assert total_tokens == record['total_generated_tokens']
        assert wasted == record['wasted_generated_tokens']
        rows.append(dict(run_id=record['run_id'], case_id=record['case_id'], policy=record['policy'],
            start_ns=start, end_ns=end[0], turn_window_seconds=(end[0]-start)/1e9,
            input_audio_seconds=source['samples']/source['sample_rate'],
            inserted_pause_seconds=case['inserted_pause_samples']/case['sample_rate'],
            tail_silence_seconds=case['tail_silence_samples']/case['sample_rate'],
            asr_calls=len(record['asr_calls']), drafts=len(drafts),
            cumulative_asr_audio_seconds=sum(c['offset']/source['sample_rate'] for c in record['asr_calls']),
            generated_tokens=total_tokens, discarded_tokens=wasted,
            selected_generation_tokens=total_tokens-wasted,
            validated_text_after_input_end_ms=(record['first_validated_text_ns']-source['input_complete_ns'])/1e6,
            speculative_selected=record['committed_draft_started_before_input_end']))
    if not rows:
        raise ValueError('no records')
    policies = {}
    for policy in sorted({r['policy'] for r in rows}):
        group = [r for r in rows if r['policy'] == policy]
        keys = ['input_audio_seconds','turn_window_seconds','inserted_pause_seconds','tail_silence_seconds',
                'asr_calls','drafts','cumulative_asr_audio_seconds','generated_tokens',
                'discarded_tokens','selected_generation_tokens']
        policies[policy] = dict(n=len(group), **{k:sum(r[k] for r in group) for k in keys},
            speculative_selected=sum(r['speculative_selected'] for r in group),
            validated_text_after_input_end_ms=distribution([r['validated_text_after_input_end_ms'] for r in group]))
    start, end = min(r['start_ns'] for r in rows), max(r['end_ns'] for r in rows)
    resident_seconds = (end-start)/1e9
    turn_seconds = sum(r['turn_window_seconds'] for r in rows)
    return dict(scope='exp17 formal batch, one resident ASR+LLM process; NOT real user sessions',
        formal_n=len(rows), policies=policies, rows=rows,
        formal_resident_window=dict(start_ns=start,end_ns=end,seconds=resident_seconds,
            excludes='model loading, warmup, residence before first/after last formal boundary'),
        turn_window_sum_seconds=turn_seconds,
        turn_window_union_seconds=union_ns([(r['start_ns'],r['end_ns']) for r in rows])/1e9,
        demo_turn_minutes=turn_seconds/60,
        input_audio_minutes=sum(r['input_audio_seconds'] for r in rows)/60,
        known_inserted_silence_seconds=sum(r['inserted_pause_seconds']+r['tail_silence_seconds'] for r in rows),
        actual_session_minutes=None, gpu_kernel_active_seconds=None,
        input_silence_is_request_idle=False, output_audio_minutes=None,
        actual_cost_per_session_minute=None,
        assumed_rate_example=assumed_cost(resident_seconds,None,2),
        assumed_cost_per_demo_turn_minute=resident_seconds/3600*2/(turn_seconds/60),
        concurrent_capacity=None)


def extract(root: Path):
    path = root / 'results/exp17/gpu-formal-v1/records.json'
    records = json.loads(path.read_text())['records']
    result = resource_ledger(records, frozen_cases(root))
    samples_path = root / 'results/exp17/gpu-formal-v1/gpu-samples.json'
    samples = json.loads(samples_path.read_text())
    window = result['formal_resident_window']
    formal = [s for s in samples if window['start_ns']<=s['monotonic_ns']<=window['end_ns']]
    result['formal_whole_card_memory_mib'] = distribution([s['memory_mib'] for s in formal])
    result['sources'] = [source_ref(p,root) for p in [path, samples_path, root/'exp14/audio/manifest.json']]
    idle_path = root / 'results/exp18/idle-v1/idle.json'
    if idle_path.exists():
        idle = json.loads(idle_path.read_text())
        result['no_new_request_probe'] = dict(n=1,seconds=idle['idle_seconds'],
            samples=len(idle['samples']),baseline_mib=idle['baseline']['memory_mib'],
            resident_memory_mib=distribution([s['memory_mib'] for s in idle['samples']]),
            utilization_percent=distribution([s['utilization_percent'] for s in idle['samples']]),
            warmup_asr_calls=1,warmup_llm_calls=1,
            source=source_ref(idle_path,root),whole_device_idle=None)
    else:
        result['no_new_request_probe'] = None
    return result
