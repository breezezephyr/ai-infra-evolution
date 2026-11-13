#!/usr/bin/env python3
"""Offline exp14 analysis. All timings are measured, same-clock differences.

CLI: python3 -B analyze.py --records records.jsonl --output summary.json
     [--browser-dir DIR] [--components DIR]
Import: analyze_records(records, browser_records=(), component_documents=()).
No inference runtime, GPU, networking or third-party Python package is required.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import unicodedata

from logic import normalized_cer

MODES = ('A', 'B', 'C')
STAGES = {
    'asr_ms': ('asr_start', 'asr_end'),
    'llm_first_text_ms': ('llm_start', 'first_text'),
    'llm_total_ms': ('llm_start', 'llm_end'),
    'tts_queue_ms': ('tts_text_submitted', 'tts_start'),
    'tts_first_pcm_ms': ('tts_start', 'first_pcm'),
    'endpoint_to_first_pcm_ms': ('endpoint_confirmed', 'first_pcm'),
    'endpoint_to_first_audio_sent_ms': ('endpoint_confirmed', 'first_audio_sent'),
    'first_pcm_to_first_audio_sent_ms': ('first_pcm', 'first_audio_sent'),
}
BROWSER_METRICS = ('first_non_silent_render_ms', 'device_output_estimate_ms',
                   'acoustic_first_sound_ms', 'underrun_count', 'underrun_duration_ms')


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def distribution(values):
    """Linear interpolation, with an explicit observation count (not case count)."""
    values = sorted(v for v in values if number(v))
    def percentile(q):
        if not values:
            return None
        position = (len(values) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)
    return {'n': len(values), 'p50': percentile(.5), 'p95': percentile(.95)}


def tri_all(values):
    values = list(values)
    if any(v is False for v in values):
        return False
    return True if values and all(v is True for v in values) else None


def tri_counts(values):
    values = list(values)
    return {'true': sum(v is True for v in values),
            'false': sum(v is False for v in values),
            'unknown': sum(v is not True and v is not False for v in values)}


def server_metrics(terminal):
    """Use event edges within this turn; preserve intervals, including overlaps."""
    events = terminal.get('events') or []
    valid, issues = [], []
    for e in events:
        if not isinstance(e, dict):
            issues.append('non-object server event')
            continue
        if any(e.get(key) is not None and terminal.get(key) is not None
               and e[key] != terminal[key]
               for key in ('session_id', 'turn_id', 'generation_id')):
            issues.append('server event belongs to another turn/generation')
            continue
        valid.append(e)

    def first(name):
        return next((e for e in valid if e.get('event') == name), None)

    def delta(a, b, label):
        if a is None or b is None:
            return None
        domain = a.get('clock_domain')
        if not domain or domain != b.get('clock_domain'):
            issues.append(label + ': missing or different clock_domain')
            return None
        start, end = a.get('monotonic_ns'), b.get('monotonic_ns')
        if type(start) is not int or type(end) is not int or end < start:
            issues.append(label + ': invalid/reversed monotonic_ns')
            return None
        return (end - start) / 1_000_000

    stages = {key: delta(first(a), first(b), key) for key, (a, b) in STAGES.items()}
    endpoint = first('endpoint_confirmed')
    last_sample = (endpoint or {}).get('last_speech_sample')
    frame = next((e for e in valid if e.get('event') == 'input_frame_received'
                  and type(last_sample) is int and type(e.get('sample_offset')) is int
                  and type(e.get('samples')) is int
                  and e['sample_offset'] < last_sample <= e['sample_offset'] + e['samples']), None)
    stages['endpoint_wait_ms'] = delta(frame, endpoint, 'endpoint_wait_ms')
    intervals = []
    for stage, a, b in [('asr', 'asr_start', 'asr_end'), ('llm', 'llm_start', 'llm_end')]:
        start, end = first(a), first(b)
        duration = delta(start, end, stage)
        if duration is not None:
            intervals.append({'stage': stage, 'clock_domain': start['clock_domain'],
                              'start_ns': start['monotonic_ns'], 'end_ns': end['monotonic_ns'],
                              'duration_ms': duration})
    start = None
    for e in valid:
        if e.get('event') == 'tts_start':
            start = e
        elif e.get('event') == 'tts_part_end' and start is not None:
            duration = delta(start, e, 'tts_part')
            if duration is not None:
                intervals.append({'stage': 'tts', 'clock_domain': start['clock_domain'],
                                  'start_ns': start['monotonic_ns'], 'end_ns': e['monotonic_ns'],
                                  'duration_ms': duration, 'text': start.get('text')})
            start = None
    return stages, intervals, issues, valid


def hash_pair(client, server):
    def valid(value):
        return (isinstance(value, str) and len(value) == 64
                and all(c in '0123456789abcdefABCDEF' for c in value))
    match = client.lower() == server.lower() if valid(client) and valid(server) else None
    return {'client': client, 'server': server, 'match': match}


def latin_answer(text):
    return (any(unicodedata.name(c, '').startswith('LATIN ') for c in text)
            if isinstance(text, str) else None)


def record_point(row, index):
    terminal = row.get('terminal') if isinstance(row.get('terminal'), dict) else {}
    state = terminal.get('state') or {}
    llm = state.get('llm') or {}
    stages, intervals, issues, events = server_metrics(terminal)
    joined = [e for e in events if e.get('event') == 'workers_joined']
    asr_returned = True if any(e.get('event') == 'asr_end' for e in events) else None
    workers = {'asr_call_returned': asr_returned,
               'llm_thread_stopped': llm.get('thread_stopped'),
               'tts_worker_returned': state.get('tts_worker_returned'),
               'tts_thread_stopped': state.get('tts_thread_stopped')}
    all_joined = tri_all([*workers.values(),
                         *(e.get(key) for e in joined for key in ('llm', 'tts'))])
    alignment = {
        'input_pcm': hash_pair(row.get('input_pcm_sha256'), terminal.get('input_pcm_sha256')),
        'output_pcm': hash_pair(row.get('output_pcm_sha256'), terminal.get('output_pcm_sha256')),
        'input_wav_sha256': row.get('input_sha256'),
        'output_samples_match': (row['output_samples'] == terminal['output_samples']
                                 if type(row.get('output_samples')) is int
                                 and type(terminal.get('output_samples')) is int else None)}
    early = row.get('endpoint_early')
    reason = terminal.get('finish_reason')
    client_error, server_error = bool(row.get('client_error')), bool(state.get('error'))
    integrity_bad = any(alignment[k]['match'] is False for k in ('input_pcm', 'output_pcm'))
    integrity_bad = integrity_bad or alignment['output_samples_match'] is False
    success = (terminal.get('type') == 'terminal' and reason == 'stop' and early is False
               and not client_error and not server_error and not integrity_bad)

    def client_delta(key):
        start, end = row.get('reference_input_end_ns'), row.get(key)
        if start is None or end is None:
            return None
        if row.get('client_clock_domain') != 'client_monotonic':
            issues.append(key + ': no client_monotonic clock evidence')
            return None
        if type(start) is not int or type(end) is not int:
            issues.append(key + ': invalid ns timestamp')
            return None
        # Negative replay values are retained as observations, never clamped to zero.
        return (end - start) / 1_000_000

    latency = client_delta('first_pcm_received_ns')
    stored = row.get('replay_end_to_first_pcm_ms')
    if number(stored) and number(latency) and not math.isclose(stored, latency, abs_tol=1e-6):
        issues.append('stored replay_end_to_first_pcm_ms disagrees with ns timestamps')
        latency = None
    reference, hypothesis = row.get('reference_text'), state.get('asr_text')
    cer = (normalized_cer(reference, hypothesis)
           if isinstance(reference, str) and isinstance(hypothesis, str) else None)
    return {'index': index, 'id': row.get('id'), 'case_id': row.get('case_id'),
            'mode': row.get('mode'), 'repeat': row.get('repeat'),
            'warmup': bool(row.get('warmup')), 'finish_reason': reason,
            'endpoint_early': early if type(early) is bool else None,
            'client_error': client_error, 'server_error': server_error,
            'success': success, 'hash_integrity_error': integrity_bad,
            'replay_end_to_first_pcm_ms': latency,
            'first_non_silent_received_ms': client_delta('first_non_silent_received_ns'),
            'server_stages_ms': stages, 'server_intervals': intervals,
            'timing_issues': issues, 'worker_evidence': workers,
            'all_workers_joined': all_joined, 'hash_alignment': alignment,
            'cer': cer, 'reference_text': reference, 'asr_text': hypothesis,
            'answer_text': state.get('text'), 'output_samples': row.get('output_samples'),
            'has_latin_answer': latin_answer(state.get('text')),
            'raw': row}


def hash_counts(points, key):
    counts = tri_counts(p['hash_alignment'][key]['match'] for p in points)
    return {'checked': counts['true'] + counts['false'], 'match': counts['true'],
            'mismatch': counts['false'], 'unknown': counts['unknown']}


def group_summary(points):
    measured = [p for p in points if not p['warmup']]
    success = [p for p in measured if p['success']]
    cases = sorted({p['case_id'] for p in measured if p['case_id'] is not None})
    reasons = Counter(p['finish_reason'] or 'missing' for p in measured)
    counts = {
        'success': len(success),
        'early': sum(p['endpoint_early'] is True for p in measured),
        'early_unknown': sum(p['endpoint_early'] is None for p in measured),
        'error': sum(p['client_error'] or p['server_error'] or p['finish_reason'] == 'error'
                     or p['hash_integrity_error'] for p in measured),
        'client_error': sum(p['client_error'] for p in measured),
        'length': reasons['length'], 'stop': reasons['stop'],
        'non_stop': sum(p['finish_reason'] != 'stop' for p in measured),
        'missing_terminal': sum(not isinstance(p['raw'].get('terminal'), dict)
                                or not p['raw']['terminal'].get('finish_reason') for p in measured)}
    cer_points = [p for p in measured if p['cer'] is not None]
    return {'n': len(measured), 'n_warmup': len(points) - len(measured),
            'n_independent_cases': len(cases),
            'n_missing_case_id': sum(p['case_id'] is None for p in measured),
            'n_independent_reference_texts': len({p['reference_text'] for p in measured
                                                if p['reference_text']}),
            'counts': counts, 'finish_reasons': dict(reasons),
            'latin_answer_rounds': sum(p['has_latin_answer'] is True for p in measured),
            'answer_text_observed_n': sum(isinstance(p['answer_text'], str) for p in measured),
            'replay_end_to_first_pcm_ms': distribution(p['replay_end_to_first_pcm_ms'] for p in success),
            'server_stages_ms': {key: distribution(p['server_stages_ms'][key] for p in success)
                                 for key in (*STAGES, 'endpoint_wait_ms')},
            'workers_joined': tri_counts(p['all_workers_joined'] for p in measured),
            'all_workers_joined': tri_all(p['all_workers_joined'] for p in measured),
            'hash_alignment': {key: hash_counts(measured, key) for key in ('input_pcm', 'output_pcm')},
            'cer': {**distribution(p['cer'] for p in cer_points),
                    'n_independent_cases': len({p['case_id'] for p in cer_points if p['case_id'] is not None}),
                    'by_case': {case: distribution(p['cer'] for p in cer_points if p['case_id'] == case)
                                for case in cases}},
            'by_case': {case: {'n': sum(p['case_id'] == case for p in measured),
                               'replay_end_to_first_pcm_ms': distribution(
                                   p['replay_end_to_first_pcm_ms'] for p in success if p['case_id'] == case)}
                        for case in cases}}


def browser_point(row):
    """Adapt playback.js runBrowserTurn export; never use precomputed deltas.

    Each mapped clock edge needs the actual anchors the client exports. There
    is currently no acoustic capture schema, so acoustic latency stays null.
    """
    times, evidence = row.get('timestamps') or {}, row.get('evidence') or {}
    terminal = row.get('terminal') if isinstance(row.get('terminal'), dict) else {}
    mapping = evidence.get('input_reference_mapping') or {}
    issues = []
    baseline = None
    if (times.get('clock_domain') == mapping.get('clock_domain') == 'browser_performance'
            and times.get('unit') == 'ms' and evidence.get('input_complete') is True
            and mapping.get('method') == 'actual_frame_send_plus_sample_offset'):
        sample, offset, count, sent = (mapping.get(k) for k in (
            'reference_sample', 'frame_sample_offset', 'frame_count', 'frame_send_performance_ms'))
        frame_present = any(f.get('sample_offset') == offset and f.get('count') == count
                            and f.get('performance_ms') == sent
                            for f in evidence.get('input_frame_sends', []))
        if (type(sample) is int and type(offset) is int and type(count) is int and count > 0
                and offset <= sample <= offset + count and number(sent) and frame_present):
            mapped = sent + (sample - offset) / 16000 * 1000
            if (number(mapping.get('performance_ms')) and number(times.get('input_reference_end_perf_ms'))
                    and math.isclose(mapped, mapping['performance_ms'], abs_tol=1e-6)
                    and math.isclose(mapped, times['input_reference_end_perf_ms'], abs_tol=1e-6)):
                baseline = mapped
    if baseline is None:
        issues.append('no complete same-clock input sample-to-performance mapping')

    def latency(value):
        return value - baseline if baseline is not None and number(value) else None

    render_event = next((e for e in evidence.get('playback_events', [])
                         if e.get('type') == 'first_non_silent_render'), None)
    render_time = None
    anchors = evidence.get('clock_anchors') or []
    if render_event is not None:
        index = render_event.get('anchor_index')
        if type(index) is int and 0 <= index < len(anchors):
            anchor = anchors[index]
            before, after, context, sound = (anchor.get('performance_before_ms'),
                                            anchor.get('performance_after_ms'),
                                            anchor.get('context_time_s'), render_event.get('context_time_s'))
            if all(number(v) for v in (before, after, context, sound)) and after >= before:
                mapped = (before + after) / 2 + (sound - context) * 1000
                stored = times.get('first_non_silent_render_perf_ms')
                if (number(stored) and number(render_event.get('performance_ms'))
                        and math.isclose(mapped, stored, abs_tol=1e-6)
                        and math.isclose(mapped, render_event['performance_ms'], abs_tol=1e-6)):
                    render_time = mapped
        if render_time is None:
            issues.append('first render has no consistent AudioContext/performance anchor')
    device_time = None
    device_index = evidence.get('first_sound_device_anchor_index')
    device_anchors = evidence.get('output_timestamp_anchors') or []
    if (render_event is not None and render_time is not None
            and evidence.get('get_output_timestamp_supported') is True
            and type(device_index) is int and 0 <= device_index < len(device_anchors)):
        anchor = device_anchors[device_index]
        context, perf = anchor.get('contextTime'), anchor.get('performanceTime')
        if number(context) and number(perf) and context >= 0 and perf > 0:
            mapped = perf + (render_event['context_time_s'] - context) * 1000
            stored = times.get('first_non_silent_device_output_estimate_perf_ms')
            if number(stored) and math.isclose(mapped, stored, abs_tol=1e-6):
                device_time = mapped
    reference_sample = mapping.get('reference_sample')
    endpoint = next((e for e in terminal.get('events', []) if e.get('event') == 'endpoint_confirmed'), {})
    endpoint_sample = endpoint.get('sample_offset')
    early = (endpoint_sample < reference_sample
             if type(endpoint_sample) is int and type(reference_sample) is int else None)
    sample_match = (terminal['output_samples'] == evidence['output_samples_received']
                    if type(terminal.get('output_samples')) is int
                    and type(evidence.get('output_samples_received')) is int else None)
    success = (terminal.get('type') == 'terminal' and terminal.get('finish_reason') == 'stop'
               and not row.get('client_error') and not (terminal.get('state') or {}).get('error')
               and early is False and evidence.get('server_terminal_received') is True
               and evidence.get('input_complete') is True and sample_match is not False)
    progress = any(e.get('type') == 'playback_progress' for e in evidence.get('playback_events', []))
    samples, rate, underruns = row.get('underrun_samples'), evidence.get('underrun_rate'), row.get('underrun_events')
    duration = (samples / rate * 1000 if progress and number(samples) and samples >= 0
                and number(rate) and rate > 0 else None)
    count = underruns if progress and type(underruns) is int and underruns >= 0 else None
    return {'id': row.get('id'), 'case_id': row.get('case_id'), 'mode': row.get('mode'),
            'source': row['source'], 'warmup': bool(row.get('warmup')), 'raw': row,
            'success': success, 'endpoint_early': early, 'finish_reason': terminal.get('finish_reason'),
            'client_error': bool(row.get('client_error')), 'timing_issues': issues,
            'replay_end_to_first_pcm_ms': latency(times.get('first_pcm_received_perf_ms')),
            'first_non_silent_render_ms': latency(render_time),
            'device_output_estimate_ms': latency(device_time), 'acoustic_first_sound_ms': None,
            'underrun_count': count, 'underrun_duration_ms': duration}


def browser_summary(records):
    points, ignored = [], []
    for row in records:
        if row.get('source') != 'browser_web_audio':
            ignored.append(row)
            continue
        points.append(browser_point(row))
    groups = {}
    for mode in MODES:
        rows = [p for p in points if p['mode'] == mode and not p['warmup']]
        success = [p for p in rows if p['success']]
        groups[mode] = {
            'n': len(rows), 'n_warmup': sum(p['mode'] == mode and p['warmup'] for p in points),
            'n_independent_cases': len({p['case_id'] for p in rows if p['case_id'] is not None}),
            'counts': {'success': len(success), 'early': sum(p['endpoint_early'] is True for p in rows),
                       'early_unknown': sum(p['endpoint_early'] is None for p in rows),
                       'error': sum(p['client_error'] or p['finish_reason'] == 'error' for p in rows),
                       'length': sum(p['finish_reason'] == 'length' for p in rows),
                       'stop': sum(p['finish_reason'] == 'stop' for p in rows)},
            **{key: distribution(p[key] for p in (rows if key.startswith('underrun') else success))
               for key in (*BROWSER_METRICS, 'replay_end_to_first_pcm_ms')}}
    return {'n': len(points), 'points': points, 'ignored': ignored,
            'schema_status': 'playback.js.runBrowserTurn.timestamps_and_evidence', 'modes': groups}


def paired_consistency(points):
    """Exact text/sample equality, never normalize away ASR punctuation changes."""
    measured = [p for p in points if not p['warmup']]
    eligible = [p for p in measured if isinstance(p['case_id'], str) and p['case_id']
                and type(p['repeat']) is int and p['mode'] in MODES]
    indexed = {}
    for p in eligible:
        indexed.setdefault((p['case_id'], p['repeat']), {}).setdefault(p['mode'], []).append(p)
    results = {}
    fields = {'asr_text_equal': ('asr_text', str), 'answer_text_equal': ('answer_text', str),
              'output_samples_equal': ('output_samples', int)}
    for a, b in [('A', 'B'), ('B', 'C')]:
        pairs, missing, ambiguous = [], [], []
        for (case, repeat), modes in sorted(indexed.items()):
            if a not in modes and b not in modes:
                continue
            counts = {m: len(modes.get(m, [])) for m in (a, b)}
            detail = {'case_id': case, 'repeat': repeat, 'counts': counts}
            if any(n > 1 for n in counts.values()):
                ambiguous.append(detail)
                continue
            if not all(counts.values()):
                missing.append(detail)
                continue
            left, right = modes[a][0], modes[b][0]
            pairs.append({**detail, 'record_ids': [left['id'], right['id']],
                          'record_indices': [left['index'], right['index']],
                          **{name: (left[key] == right[key] if type(left[key]) is dtype
                                     and type(right[key]) is dtype else None)
                             for name, (key, dtype) in fields.items()}})
        results[f'{a}/{b}'] = {
            'n_keys': len(pairs) + len(missing) + len(ambiguous), 'n_pairs': len(pairs),
            'n_missing': len(missing), 'n_ambiguous': len(ambiguous),
            'n_unkeyed_records': sum(p not in eligible and p['mode'] in (a, b) for p in measured),
            **{name: tri_counts(p[name] for p in pairs) for name in fields},
            'points': pairs, 'missing': missing, 'ambiguous': ambiguous}
    return results


def component_summary(documents):
    reports, ignored = [], []
    fields = {'asr_ms': ('asr', 'ms'), 'llm_first_text_ms': ('llm', 'first_text_ms'),
              'llm_total_ms': ('llm', 'total_ms'), 'tts_first_pcm_ms': ('tts', 'first_pcm_ms'),
              'tts_total_ms': ('tts', 'total_ms')}
    for doc in documents:
        if doc.get('kind') != 'actual_cuda_component_smoke' or doc.get('component') not in ('asr', 'llm', 'tts', 'resident'):
            ignored.append(doc)
            continue
        records = doc.get('records') or []
        measured = [r for r in records if r.get('warmup') is False]
        component = doc['component']
        timings = {name: distribution(r.get(part, {}).get(key) for r in measured)
                   for name, (part, key) in fields.items() if component in (part, 'resident')}
        models = doc.get('models') or {}
        parts = ('asr', 'llm', 'tts') if component == 'resident' else (component,)
        devices = [models.get(part, {}).get('device') for part in parts]
        cuda_verified = all(isinstance(d, str) and d.split(':')[0] == 'cuda' for d in devices)
        reports.append({'component': component,
                        'scope': 'resident' if component == 'resident' else 'independent',
                        'cuda_device_evidence': cuda_verified,
                        'n': len(measured), 'n_warmup': sum(r.get('warmup') is True for r in records),
                        'n_warmup_unknown': sum(type(r.get('warmup')) is not bool for r in records),
                        'timings': timings, 'raw_records': records,
                        'raw_metadata': {k: v for k, v in doc.items() if k != 'records'}})
    return {'reports': reports, 'ignored': ignored}


def analyze_records(records, browser_records=(), component_documents=()):
    points = [record_point(row, index) for index, row in enumerate(records)]
    return {'schema_version': 1, 'kind': 'exp14_measured_summary',
            'n_records': len(points),
            'modes': {mode: group_summary([p for p in points if p['mode'] == mode]) for mode in MODES},
            'unassigned_record_indices': [p['index'] for p in points if p['mode'] not in MODES],
            'points': points, 'browser': browser_summary(browser_records),
            'paired_consistency': paired_consistency(points),
            'latin_answer_rounds': sum(p['has_latin_answer'] is True and not p['warmup'] for p in points),
            'components': component_summary(component_documents),
            'notes': {
                'denominators': 'n excludes warmup only; counts overlap (stop may also be early/error). All raw points retained.',
                'success': 'terminal stop AND endpoint_early explicitly false AND no client/server/hash error.',
                'latency': 'Success-only p50/p95; linear interpolation with explicit n. Same client monotonic ns only; no zero imputation.',
                'independence': 'Repeated timings are observations, not independent texts. Case IDs and exact reference texts counted separately.',
                'server': 'Same-clock monotonic_ns event edges. endpoint_wait starts at receipt of the frame containing VAD last_speech_sample, not reference last sound. Never sum stage percentiles.',
                'cer': 'logic.normalized_cer: NFKC, lowercase, remove Unicode punctuation and whitespace; no traditional/simplified conversion. Missing transcript/reference is null.',
                'workers': 'ASR call return event plus actual LLM/TTS thread-stop and TTS return evidence; unknown is not joined. Join does not mean resident weights freed.',
                'hashes': 'Compare input_pcm_sha256 with terminal.input_pcm_sha256, and output PCM likewise. input_sha256 hashes the WAV container and is never compared with PCM.',
                'browser': 'Web Audio render, device output estimate and acoustic loopback are separate. Missing measurements remain null.',
                'paired_consistency': 'Exact ASR/answer text and output sample equality within case_id+repeat, excluding warmup. Missing/duplicate modes are explicit. Differences may reflect content/segmentation changes; do not attribute every latency difference solely to waiting.',
                'tts_latin': 'Known Chinese TTS frontend limitation: en_callable=None may skip English. Count rounds containing Unicode Latin letters in actual answer text, excluding warmup, including failed rounds; no audio quality score is inferred.',
                'components': 'Independent and resident documents stay separate; only explicit warmup=false rows timed. Observed memory peak is sampled, not an allocation maximum.'}}


def read_json(path, sources, jsonl=False):
    path = Path(path)
    payload = path.read_bytes()
    sources.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(payload).hexdigest(),
                    'bytes': len(payload)})
    text = payload.decode('utf-8')
    if jsonl:
        rows = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'{path}:{line_number}: {exc}') from exc
            if not isinstance(row, dict):
                raise ValueError(f'{path}:{line_number}: expected JSON object')
            rows.append(row)
        return rows
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc


def read_directory(directory, sources):
    if directory is None:
        return []
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f'{directory}: expected directory')
    rows = []
    for path in sorted(directory.rglob('*')):
        if path.suffix not in ('.json', '.jsonl') or not path.is_file():
            continue
        data = read_json(path, sources, path.suffix == '.jsonl')
        for row in data if isinstance(data, list) else [data]:
            if not isinstance(row, dict):
                raise ValueError(f'{path}: expected object(s)')
            rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', required=True, type=Path)
    parser.add_argument('--browser-dir', type=Path)
    parser.add_argument('--components', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    sources = []
    try:
        records = read_json(args.records, sources, jsonl=True)
        browser = read_directory(args.browser_dir, sources)
        components = read_directory(args.components, sources)
        result = analyze_records(records, browser, components)
        result['sources'] = sources
        if args.output.resolve() in {Path(s['path']) for s in sources}:
            raise ValueError('output must not overwrite an input')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'{exc}\n')
    print(args.output)


if __name__ == '__main__':
    main()
