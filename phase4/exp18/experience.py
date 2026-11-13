"""Offline exp14/15 experience ledger. extract(root=phase4) returns JSON data.

Only named final raw captures are inputs. No network, GPU, or summary reads.
All percentiles use linear interpolation on eligible observed whole intervals.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def distribution(values):
    values = list(values)
    data = sorted(v for v in values if numeric(v))
    def quantile(q):
        if not data:
            return None
        position = (len(data) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        return data[lo] + (data[hi] - data[lo]) * (position - lo)
    return dict(n=len(values), eligible=len(values), measured=len(data),
                unknown=len(values)-len(data), p50=quantile(.5), p95=quantile(.95))


def tri_all(values):
    values = list(values)
    if any(v is False for v in values):
        return False
    return True if values and all(v is True for v in values) else None


def equal(a, b):
    return a == b if a is not None and b is not None else None


def hash_match(a, b):
    def valid(value):
        return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower())
    return a.lower() == b.lower() if valid(a) and valid(b) else None


def event(row, name):
    return next((e for e in row.get('events', []) if e.get('event') == name), {})


def delta(start, end, clock, expected, scale=1):
    if clock != expected or not numeric(start) or not numeric(end):
        return None
    return (end-start) / scale


def metadata(points, clock, definition, unit):
    return dict(clock=clock, definition=definition, unit=unit,
                source_paths=sorted({p['source']['path'] for p in points if p.get('source')}))


def signal(points, key, clock, definition, unit='ms'):
    values = [p.get(key) if p.get('success') is True else None for p in points]
    result = distribution(values)
    failures = sum(p.get('success') is False for p in points)
    result.update(metadata(points, clock, definition, unit))
    result.update(failures=failures, unknown=result['unknown']-failures)
    return result


def boolean_signal(points, key, definition):
    passed = sum(p.get(key) is True for p in points)
    failed = sum(p.get(key) is False for p in points)
    return dict(n=len(points), passed=passed, failures=failed, unknown=len(points)-passed-failed,
                **metadata(points, 'source sample indices / terminal state; no clock subtraction',
                           definition, 'count'))


def candidate(points, key='first_pcm_ms'):
    states = [False if p.get('success') is False else
              (p[key] <= 800 if p.get('success') is True and numeric(p.get(key)) and p[key] >= 0
               else None) for p in points]
    passed, failed = sum(s is True for s in states), sum(s is False for s in states)
    return dict(n=len(points), eligible=len(points), passed=passed, failed=failed, failures=failed,
                unknown=len(points)-passed-failed, threshold_ms=800,
                all_observations_pass=tri_all(states), exploration_only=True,
                production_compliance=None,
                **metadata(points, 'same client clock within each observation',
                           'Complete endpoint AND natural stop AND integrity/no-error checks AND '
                           'observed nonnegative reference-end to first-PCM <=800ms; full cohort denominator. '
                           '800ms is an exploratory threshold, not a production SLO.', 'count'))


def formal_turn(row, case, source=None):
    terminal = row.get('terminal') or {}
    edges = [e for e in terminal.get('events', []) if e.get('event') == 'endpoint_confirmed'
             and all(e.get(k) is None or terminal.get(k) is None or e[k] == terminal[k]
                     for k in ('session_id', 'turn_id', 'generation_id'))]
    intervals, rate = case.get('speech_intervals') or [], case.get('sample_rate')
    reference_sample = intervals[-1].get('end') if intervals else None
    offset = edges[0].get('sample_offset') if len(edges) == 1 else None
    complete = offset >= reference_sample if type(offset) is int and type(reference_sample) is int else None
    stop = (terminal.get('type') == 'terminal' and terminal['finish_reason'] == 'stop'
            if terminal.get('finish_reason') is not None else None)
    integrity = tri_all([hash_match(row.get(k), terminal.get(k)) for k in
                         ('input_pcm_sha256', 'output_pcm_sha256')]
                        + [equal(row.get('output_samples'), terminal.get('output_samples')),
                           hash_match(row.get('input_sha256'), case.get('sha256'))])
    success = tri_all([complete, stop, integrity,
                       not bool(row.get('client_error') or (terminal.get('state') or {}).get('error'))])
    clock = row.get('client_clock_domain')
    start = row.get('reference_input_end_ns')
    expected = (row['input_start_ns'] + round(reference_sample/rate*1e9)
                if type(row.get('input_start_ns')) is int and type(reference_sample) is int
                and numeric(rate) and rate > 0 else None)
    issues = []
    if expected is None or start != expected:
        start = None
        issues.append('missing/inconsistent input start + offline energy reference sample mapping')
    latency = delta(start, row.get('first_pcm_received_ns'), clock, 'client_monotonic', 1e6)
    if latency is None:
        issues.append('missing same-client monotonic first-PCM interval')
    if complete is None:
        issues.append('missing/ambiguous endpoint sample boundary')
    return dict(id=row.get('id'), mode=row.get('mode'), case_id=row.get('case_id'),
                repeat=row.get('repeat'), source=source, endpoint_complete=complete,
                endpoint_early=not complete if type(complete) is bool else None,
                stop=stop, success=success, integrity=integrity, first_pcm_ms=latency,
                reference_sample=reference_sample, reference_end_ns=start,
                first_pcm_received_ns=row.get('first_pcm_received_ns'), clock=clock, issues=issues)


def summarize_turns(points):
    return dict(n=len(points), counts=dict(stop=sum(p.get('stop') is True for p in points),
                early=sum(p.get('endpoint_early') is True for p in points),
                endpoint_complete=sum(p.get('endpoint_complete') is True for p in points),
                success=sum(p.get('success') is True for p in points),
                failures=sum(p.get('success') is False for p in points),
                unknown=sum(p.get('success') is None for p in points)),
                endpoint_completeness=boolean_signal(points, 'endpoint_complete',
                    'endpoint_confirmed.sample_offset >= offline energy-reference last speech sample'),
                terminal_stop=boolean_signal(points, 'stop', 'terminal.type=terminal AND finish_reason=stop'),
                first_pcm_ms=signal(points, 'first_pcm_ms', 'client_monotonic, one process per raw turn',
                    'first_pcm_received_ns - (input_start_ns + offline energy-reference sample/rate). '
                    'Synthetic paced-input reference; successful complete turns only; not acoustic first sound.'),
                candidate_800ms=candidate(points))


def browser_turn(row, source=None):
    times, ev = row.get('timestamps') or {}, row.get('evidence') or {}
    mapping, terminal = ev.get('input_reference_mapping') or {}, row.get('terminal') or {}
    baseline = None
    sample, offset, count, sent = [mapping.get(k) for k in
        ('reference_sample', 'frame_sample_offset', 'frame_count', 'frame_send_performance_ms')]
    if (times.get('clock_domain') == mapping.get('clock_domain') == 'browser_performance'
            and times.get('unit') == 'ms' and ev.get('input_complete') is True
            and mapping.get('method') == 'actual_frame_send_plus_sample_offset'
            and all(type(v) is int for v in (sample, offset, count)) and count > 0
            and offset <= sample <= offset+count and numeric(sent)
            and any(f.get('sample_offset') == offset and f.get('count') == count
                    and f.get('performance_ms') == sent for f in ev.get('input_frame_sends', []))):
        computed = sent + (sample-offset)/16000*1000
        if all(numeric(v) and math.isclose(v, computed, abs_tol=1e-6) for v in
               (mapping.get('performance_ms'), times.get('input_reference_end_perf_ms'))):
            baseline = computed
    render = next((e for e in ev.get('playback_events', [])
                   if e.get('type') == 'first_non_silent_render'), {})
    render_clock_valid = render.get('clock_domain', 'browser_performance') == 'browser_performance'
    calibrated = None
    anchors, index = ev.get('clock_anchors') or [], render.get('anchor_index')
    if render_clock_valid and type(index) is int and 0 <= index < len(anchors):
        anchor = anchors[index]
        before, after, context, sound = [anchor.get('performance_before_ms'),
            anchor.get('performance_after_ms'), anchor.get('context_time_s'), render.get('context_time_s')]
        if all(numeric(v) for v in (before, after, context, sound)) and after >= before:
            value = (before+after)/2 + (sound-context)*1000
            if all(numeric(v) and math.isclose(v, value, abs_tol=1e-6) for v in
                   (render.get('performance_ms'), times.get('first_non_silent_render_perf_ms'))):
                calibrated = value
    endpoint = event(terminal, 'endpoint_confirmed').get('sample_offset')
    complete = endpoint >= sample if type(endpoint) is int and type(sample) is int else None
    stop = (terminal.get('type') == 'terminal' and terminal['finish_reason'] == 'stop'
            if terminal.get('finish_reason') is not None else None)
    success = tri_all([complete, stop, ev.get('input_complete'), ev.get('server_terminal_received'),
        equal(terminal.get('output_samples'), ev.get('output_samples_received')),
        not bool(row.get('client_error') or (terminal.get('state') or {}).get('error'))])
    def latency(value):
        return value-baseline if numeric(value) and baseline is not None else None
    return dict(id=row.get('id'), mode=row.get('mode'), source=source, success=success,
                stop=stop, endpoint_complete=complete,
                endpoint_early=not complete if type(complete) is bool else None,
                first_pcm_ms=latency(times.get('first_pcm_received_perf_ms')),
                first_non_silent_render_ms=latency(calibrated),
                first_render_notification_ms=latency(render.get('observed_performance_ms'))
                    if render_clock_valid else None,
                acoustic_first_sound_ms=None,
                issues=[] if baseline is not None else ['missing same-browser reference mapping'])


def rtc_counters(row):
    def inbound(stats):
        return [s for s in stats if s.get('type') == 'inbound-rtp'
                and s.get('kind', s.get('mediaType')) == 'audio']
    ends = inbound(row.get('rtc_stats_end') or [])
    end = ends[0] if len(ends) == 1 else {}
    starts = [s for s in inbound(row.get('rtc_stats_start') or [])
              if end.get('id') is not None and s.get('id') == end['id']]
    start = starts[0] if len(starts) == 1 else {}
    keys = ('concealedSamples', 'packetsReceived', 'packetsLost', 'jitterBufferDelay',
            'jitterBufferEmittedCount')
    differences = {k: end[k]-start[k] if numeric(end.get(k)) and numeric(start.get(k))
                   and (end[k] >= start[k] or k == 'packetsLost') else None for k in keys}
    return dict(start_present=bool(start), end={k: end.get(k) for k in keys}, delta=differences)


def media_turn(row, server, source=None):
    fixture, playback = row.get('fixture') or {}, row.get('playback') or {}
    expected, produced = fixture.get('samples'), server.get('produced_samples')
    source_complete = tri_all([equal(expected, produced), equal(expected, server.get('fixture_samples')),
        *[equal(row.get(k), server.get(k)) for k in ('run_id', 'transport', 'scenario', 'fixture_id')]])
    if row.get('transport') == 'ws':
        playback_complete = tri_all([equal(expected, row.get('received_samples')),
                                    equal(expected, playback.get('consumed'))])
    else:
        done, final = row.get('producer_done_received_ms'), event(row, 'client_finished').get('performance_ms')
        rate = row.get('context_rate')
        frames = [playback.get(k) for k in ('first_frame', 'end_probe_frame', 'sample_frame')]
        if (all(numeric(v) for v in frames) and numeric(rate) and rate > 0
                and numeric(expected) and numeric(fixture.get('rate')) and fixture['rate'] > 0
                and numeric(fixture.get('tail_guard_seconds'))):
            first, probe, finish = frames
            guard = (finish-probe)/rate*1000
            expected_probe = (expected/fixture['rate']-fixture['tail_guard_seconds'])*1000
            expected_probe += 200 if row.get('scenario') == 'source_pause' else 0
            plausible = abs((probe-first)/rate*1000-expected_probe) <= 250
        else:
            guard, plausible = None, None
        playback_complete = tri_all([bool(event(row, 'producer_done_received')) or None,
            done <= final if numeric(done) and numeric(final) else None,
            250 <= guard <= 260 if numeric(guard) else None, plausible])
    complete = row.get('outcome') == 'complete' if row.get('outcome') is not None else None
    success = tri_all([complete, not bool(row.get('error')), source_complete, playback_complete])
    # This frozen schema's *_performance_ms fields are recorded with performance.now()
    # in client.js. Explicit contradictory clock declarations invalidate the interval.
    clock = row.get('clock_domain', 'browser_performance')
    latency = delta(row.get('media_start_performance_ms'),
                    row.get('first_render_notification_performance_ms'), clock, 'browser_performance')
    if numeric(latency) and latency < 0:
        latency = None
    samples, rate = playback.get('underrun_samples'), row.get('context_rate')
    underrun = samples/rate*1000 if row.get('transport') == 'ws' and numeric(samples) and samples >= 0 \
        and numeric(rate) and rate > 0 else None
    rtc = rtc_counters(row) if row.get('transport') == 'rtc' else None
    return dict(id=row.get('run_id'), source=source, transport=row.get('transport'),
                scenario=row.get('scenario'), fixture_id=row.get('fixture_id'), repeat=row.get('repeat'),
                success=success, source_complete=source_complete, source_samples=produced,
                expected_source_samples=expected, start_to_first_render_ms=latency,
                connect_reported_ms=row.get('connect_ms'), ws_underrun_ms=underrun,
                rtc_concealed_end=rtc['end']['concealedSamples'] if rtc else None,
                rtc_concealed_delta=rtc['delta']['concealedSamples'] if rtc else None,
                rtc=rtc, rtc_bit_exact_source_ack=None)


def drain_ledger(row, source):
    producer = event(row, 'producer_done_observed')
    finished = next((e for e in row.get('events', []) if e.get('event') == 'worklet'
                     and (e.get('observation') or {}).get('type') == 'finished'), {})
    initial = event(row, 'initial_buffer_released')
    audio = next((e.get('message', {}).get('audio') for e in row.get('events', [])
                  if e.get('message', {}).get('audio')), {})
    source_samples, consumed = audio.get('total_samples'), finished.get('observation', {}).get('consumed')
    received = [e for e in row.get('events', []) if e.get('event') == 'audio_received']
    received_samples = sum(e['sample_count'] for e in received) if received and all(
        type(e.get('sample_count')) is int and e['sample_count'] >= 0 for e in received) else None
    played = row.get('played') or {}
    worker = ((row.get('done') or {}).get('terminal') or {}).get('worker') or {}
    success = tri_all([equal(source_samples, received_samples), equal(source_samples, consumed),
                       equal(consumed, played.get('played_samples_cumulative')),
                       played.get('ack_source') == 'audio_worklet_consumed',
                       worker.get('status') == 'drained', worker.get('drained')])
    value = delta(producer.get('performance_ms'), finished.get('performance_ms'),
                  row.get('clock_domain', 'browser_performance'), 'browser_performance')
    point = dict(source=source, success=success, value=value)
    latest = producer.get('played_samples_cumulative')
    return dict(n=1, source=source, source_samples=source_samples,
                received_samples=received_samples, rendered_samples=consumed,
                latest_report_consumed_samples=latest,
                latest_report_unrendered_samples=source_samples-latest
                    if numeric(source_samples) and numeric(latest) else None,
                instantaneous_queue_exact=False, initial_buffer_ms=initial.get('initial_buffer_ms'),
                ack_source=played.get('ack_source'), worker_status=worker.get('status'),
                acoustic_first_sound_ms=None,
                producer_done_to_finished_ms=signal([point], 'value', 'browser_performance; session-client.js',
                    'worklet finished notification.performance_ms - producer_done_observed.performance_ms; '
                    'n=1 actual AudioWorklet consumption, includes message dispatch; not acoustic tail.'))


def control_ledger(rows, path):
    forced, drained = [], []
    for index, row in enumerate(rows, 1):
        if row.get('event') == 'session_forced':
            session = row.get('session') or {}
            turn = session.get('turn') or {}
            forced.append(dict(source=dict(path=path, line=index), status=session.get('status'),
                reason=session.get('reason'), source_samples=turn.get('total_samples'),
                sent_samples=turn.get('sent_samples'), synthetic_ack_samples=turn.get('played_samples'),
                unacknowledged_samples=session.get('unplayed_samples'),
                audio_loss_samples=None, included_in_browser_drain=False))
        if row.get('event') in ('worker_drained', 'worker_forced'):
            worker = row.get('worker') or {}
            drained.append(dict(source=dict(path=path, line=index), owner=row.get('owner'),
                                status=worker.get('status'), drained=worker.get('drained')))
    scheduled = [r for r in rows if r.get('event') == 'deadline_scheduled' and r.get('deadline_ms') == 200]
    times = []
    for start in scheduled:
        end = next((r for r in rows if r.get('event') == 'deadline_fired'
                    and r.get('owner') == start.get('owner')
                    and r.get('deadline_monotonic_ns') == start.get('deadline_monotonic_ns')), {})
        times.append(dict(source=dict(path=path), success=bool(end) or None,
            value=delta(start.get('monotonic_ns'), end.get('monotonic_ns'),
                        'server_monotonic', 'server_monotonic', 1e6)))
    return dict(n_forced=len(forced), forced=forced, worker_terminal_states=drained,
                clock='server_monotonic; session_http.py',
                definition='Synthetic Python ACK control; forced is separate from normal drained. '
                           'Unacknowledged samples are not measured acoustic loss.',
                failures=0, unknown=0,
                deadline_200ms=signal(times, 'value', 'server_monotonic; session_http.py',
                    'deadline_fired.monotonic_ns - deadline_scheduled.monotonic_ns, same server process.'))


def extract(root: Path):
    root = Path(root)
    sources = {}
    def load(relative, jsonl=False):
        path = root / relative
        raw = path.read_bytes()
        sources[relative] = dict(path=relative, sha256=hashlib.sha256(raw).hexdigest())
        if jsonl:
            return [(i, json.loads(s)) for i, s in enumerate(raw.decode().splitlines(), 1) if s.strip()]
        return json.loads(raw)
    manifest = load('exp14/audio/manifest.json')
    cases = {c['id']: c for c in manifest['cases']}
    path = 'results/exp14/live-final-v1/records.jsonl'
    records = load(path, True)
    formal = [formal_turn(r, cases[r['case_id']], dict(path=path, line=line))
              for line, r in records if r.get('warmup') is False]
    expected = set(itertools.product(cases, range(3), 'ABC'))
    keys = [(p['case_id'], p['repeat'], p['mode']) for p in formal]
    if len(set(keys)) != len(keys) or not set(keys) <= expected:
        raise ValueError('duplicate/unexpected exp14 final formal cells')
    for case, repeat, mode in sorted(expected-set(keys)):
        formal.append(dict(id=None, case_id=case, repeat=repeat, mode=mode, success=None,
                           source=dict(path=path), issues=['missing expected formal record']))
    formal_result = summarize_turns(formal)
    formal_result.update(n_expected=len(expected), n_raw_formal=len(keys),
                         n_warmup=sum(r.get('warmup') is True for _, r in records),
                         by_mode={m: summarize_turns([p for p in formal if p['mode'] == m]) for m in 'ABC'},
                         rows=formal,
                         reference_definition='Offline synthetic input energy reference: non-overlapping '
                         '10ms RMS windows, PCM16 threshold 120; mapped via input_start_ns + sample/rate '
                         'in the capture client monotonic clock. Not live microphone endpoint/acoustic onset.')
    browser_points = []
    for p in sorted((root/'results/exp14/server-eof-fixed').glob('browser-browser-*.json')):
        relative = str(p.relative_to(root))
        row = load(relative)
        if row.get('source') == 'browser_web_audio':
            browser_points.append(browser_turn(row, dict(path=relative)))
    browser_result = dict(n=len(browser_points), n_expected=3, rows=browser_points, by_mode={})
    for mode in 'ABC':
        points = [p for p in browser_points if p['mode'] == mode]
        group = summarize_turns(points)
        for key, definition in [
            ('first_non_silent_render_ms', 'Calibrated AudioContext first non-silent sample mapped by '
             'bracketed performance anchors minus actual-send/sample input reference.'),
            ('first_render_notification_ms', 'Main-thread observed_performance_ms for first non-silent '
             'render notification minus same-browser actual-send/sample input reference.'),
            ('acoustic_first_sound_ms', 'No acoustic loopback captured; always unknown.')]:
            group[key] = signal(points, key, 'browser_performance, within each browser turn', definition)
        # The capture-client clock label from summarize_turns does not apply to these rows.
        group['first_pcm_ms'].update(clock='browser_performance', definition=
            'first_pcm_received_perf_ms - validated actual frame-send/sample reference in this browser.')
        browser_result['by_mode'][mode] = group
    path = 'results/exp15/browser-formal-v2/records.json'
    document = load(path)
    if document.get('mode') != 'formal' or not document.get('endedAt'):
        raise ValueError('exp15 named final batch is not a completed formal capture')
    points = []
    for index, row in enumerate(document['records']):
        server_path = f'results/exp15/media-server-formal/server-{row["run_id"]}.json'
        point = media_turn(row, load(server_path), dict(path=path, pointer=f'/records/{index}'))
        point['server_source'] = dict(path=server_path)
        points.append(point)
    expected = set(itertools.product(('ws', 'rtc'), ('baseline', 'source_pause'), ('short', 'long'), range(3)))
    keys = [(p['transport'], p['scenario'], p['fixture_id'], p['repeat']) for p in points]
    if len(set(keys)) != len(keys) or not set(keys) <= expected:
        raise ValueError('duplicate/unexpected exp15 final media cells')
    for transport, scenario, fixture, repeat in sorted(expected-set(keys)):
        points.append(dict(transport=transport, scenario=scenario, fixture_id=fixture, repeat=repeat,
                           success=None, source=dict(path=path)))
    groups = {}
    definitions = dict(start_to_first_render_ms=('browser_performance; client.js',
        'first_render_notification_performance_ms - media_start_performance_ms; pre-generated media '
        'probe, includes main-thread dispatch; not user end-of-speech or acoustic latency.', 'ms'),
        connect_reported_ms=('browser_performance; client.js', 'Raw client connect_ms = ready_ms - '
            'startedPerf, includes player preparation/80ms warmup. startedPerf was not persisted; '
            'this scalar is reported, not independently recomputed.', 'ms'),
        ws_underrun_ms=('AudioWorklet source samples / context_rate',
            '1000 * playback.underrun_samples / context_rate; empty queue after playback starts '
            'and before expected source consumption. Different definition from RTC concealment.', 'ms'),
        rtc_concealed_end=('RTC inbound-rtp cumulative end snapshot',
            'End concealedSamples snapshot, diagnostic only; not interval or WS underrun duration.', 'samples'),
        rtc_concealed_delta=('RTC matched inbound-rtp stream counters',
            'End minus start concealedSamples for matching inbound audio id; absent start => null.', 'samples'))
    for transport, scenario in itertools.product(('ws', 'rtc'), ('baseline', 'source_pause')):
        selected = [p for p in points if p['transport'] == transport and p['scenario'] == scenario]
        group = dict(n=len(selected), n_expected=6, failures=sum(p['success'] is False for p in selected),
                     unknown=sum(p['success'] is None for p in selected))
        metric_keys = ['start_to_first_render_ms', 'connect_reported_ms']
        metric_keys += ['ws_underrun_ms'] if transport == 'ws' else ['rtc_concealed_end', 'rtc_concealed_delta']
        for key in metric_keys:
            clock, definition, unit = definitions[key]
            group[key] = signal(selected, key, clock, definition, unit)
        group['by_fixture'] = {}
        for fixture in ('short', 'long'):
            subset = [p for p in selected if p['fixture_id'] == fixture]
            group['by_fixture'][fixture] = {key: signal(subset, key, *definitions[key]) for key in metric_keys}
        groups[f'{transport}/{scenario}'] = group
    drain_path = 'results/exp15/sessions/browser-playback/record.json'
    drain = drain_ledger(load(drain_path), dict(path=drain_path))
    control_path = 'results/exp15/sessions/http-ws-final/server-events.jsonl'
    control = control_ledger([r for _, r in load(control_path, True)], control_path)
    # Keep clock-schema evidence and the consulted field definitions reproducible.
    for relative in ('exp14/run.py', 'exp14/playback.js', 'exp14/prepare_audio.py', 'exp14/analyze.py',
                     'exp15/client.js', 'exp15/session-client.js', 'exp15/session_http.py', 'exp15/analyze.py'):
        raw = (root/relative).read_bytes()
        sources[relative] = dict(path=relative, sha256=hashlib.sha256(raw).hexdigest(), role='field/clock definition')
    return dict(schema_version='exp18.experience.v1',
                exp14=dict(formal=formal_result, browser=browser_result),
                exp15=dict(media=dict(n=len(points), n_expected=24, groups=groups, rows=points),
                           drain=drain, control=control), sources=list(sources.values()),
                limitations=['800ms is exploratory only; production compliance is unknown.',
                    'No acoustic loopback or perceptual quality measurement.',
                    'exp14 capture and browser, exp15 media and control/drain are separate cohorts.',
                    'RTC absent initial inbound-rtp cannot support interval concealment/loss/jitter metrics.',
                    'Only named final directories; pilots, earlier versions and old summaries are excluded.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(extract(args.root), ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
