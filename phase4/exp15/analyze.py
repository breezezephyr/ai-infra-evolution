#!/usr/bin/env python3
"""Offline exp15 analysis; fixed inputs, no services, GPU, or network calls.

Final output is gated on browser-formal-v2 ending with all 24 runs complete,
all RTC producer_done controls received, and all named server sample counts full.
Run with /tmp/exp14-local-env/bin/python -B phase4/exp15/analyze.py.
--check only reports readiness; it never writes a partial summary.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

PHASE4 = Path(__file__).resolve().parents[1]
RESULTS = PHASE4 / 'results' / 'exp15'
FINAL_RECORDS = RESULTS / 'browser-formal-v2' / 'records.json'
FINAL_OUTPUT = PHASE4 / 'results' / 'exp15-summary.json'
SCENARIOS = ('baseline', 'source_pause')
TRANSPORTS = ('ws', 'rtc')
FIXTURES = ('short', 'long')
COUNTERS = (
    'jitterBufferDelay', 'jitterBufferEmittedCount', 'jitterBufferTargetDelay',
    'jitterBufferMinimumDelay', 'concealedSamples', 'silentConcealedSamples',
    'concealmentEvents', 'packetsReceived', 'packetsLost', 'packetsDiscarded',
    'bytesReceived', 'headerBytesReceived', 'totalSamplesReceived',
    'insertedSamplesForDeceleration', 'removedSamplesForAcceleration',
)
PROBE_TOLERANCE_MS = 250  # Explicit plausibility screen, not a detector accuracy claim.


class EvidenceError(ValueError):
    pass


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def provenance(path):
    path = Path(path)
    return {'path': str(path.relative_to(PHASE4.parent)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def distribution(values):
    """Preserve repeat order and nulls; p50 only uses observed finite values."""
    values = list(values)
    observed = [v for v in values if numeric(v)]
    return {'n': len(values), 'n_observed': len(observed),
            'n_missing': len(values) - len(observed), 'values': values,
            'p50': statistics.median(observed) if observed else None}


def ratio(numerator, denominator, scale=1):
    if not numeric(numerator) or not numeric(denominator) or denominator <= 0:
        return None
    return scale * numerator / denominator


def event(record, name):
    return next((e for e in record.get('events', []) if e.get('event') == name), None)


def rtc_stats(record):
    """Difference matched inbound streams; never invent a zero start snapshot."""
    start_stats = record.get('rtc_stats_start') or []
    end_stats = record.get('rtc_stats_end') or []
    inbound_end = [s for s in end_stats if s.get('type') == 'inbound-rtp'
                   and s.get('kind', s.get('mediaType')) == 'audio']
    end = inbound_end[0] if len(inbound_end) == 1 else {}
    inbound_start = [s for s in start_stats if s.get('type') == 'inbound-rtp'
                     and s.get('kind', s.get('mediaType')) == 'audio'
                     and s.get('id') == end.get('id')]
    start = inbound_start[0] if len(inbound_start) == 1 else {}
    issues = []
    if not start:
        issues.append('missing_matched_inbound_rtp_start')
    if not end:
        issues.append('missing_or_ambiguous_inbound_rtp_end')
    deltas = {}
    for key in COUNTERS:
        a, b = start.get(key), end.get(key)
        value = b - a if numeric(a) and numeric(b) else None
        if numeric(value) and value < 0 and key != 'packetsLost':
            issues.append('counter_decreased:' + key)
            value = None
        deltas[key] = value
    deltas['jitter_buffer_mean_delay_ms'] = ratio(
        deltas['jitterBufferDelay'], deltas['jitterBufferEmittedCount'], 1000)
    received, lost = deltas['packetsReceived'], deltas['packetsLost']
    denominator = received + lost if numeric(received) and numeric(lost) else None
    deltas['packet_loss_fraction'] = ratio(lost, denominator)
    deltas['packet_loss_denominator'] = denominator
    index = {s.get('id'): s for s in end_stats}
    transport = index.get(end.get('transportId'), {})
    if not transport:
        candidates = [s for s in end_stats if s.get('type') == 'transport'
                      and s.get('selectedCandidatePairId')]
        transport = candidates[0] if len(candidates) == 1 else {}
    pair = index.get(transport.get('selectedCandidatePairId'), {})
    local = index.get(pair.get('localCandidateId'), {})
    remote = index.get(pair.get('remoteCandidateId'), {})
    codec = index.get(end.get('codecId'), {})
    path = {
        'selection_basis': 'transport.selectedCandidatePairId' if pair else None,
        'candidate_pair_id': pair.get('id'), 'state': pair.get('state'),
        'local_protocol': local.get('protocol'), 'local_type': local.get('candidateType'),
        'remote_protocol': remote.get('protocol'), 'remote_type': remote.get('candidateType'),
        'codec': {k: codec.get(k) for k in
                  ('mimeType', 'clockRate', 'channels', 'payloadType', 'sdpFmtpLine')},
    }
    return {'inbound_start_present': bool(start), 'inbound_end_present': bool(end),
            'start': {k: start.get(k) for k in COUNTERS},
            'end': {k: end.get(k) for k in COUNTERS},
            'delta': deltas, 'path': path, 'issues': issues}


def sample_integrity(record, server):
    fixture, playback = record['fixture'], record.get('playback') or {}
    expected = fixture['samples']
    for key in ('run_id', 'fixture_id', 'transport', 'scenario'):
        require(server.get(key) == record.get(key), f'{record["run_id"]}: server {key} mismatch')
    require(server.get('fixture_samples') == expected, 'server fixture_samples mismatch')
    rate = record.get('context_rate')
    first, probe, finish = (playback.get(k) for k in
                            ('first_frame', 'end_probe_frame', 'sample_frame'))
    probe_elapsed = ratio(probe - first, rate, 1000) if numeric(first) and numeric(probe) else None
    guard = ratio(finish - probe, rate, 1000) if numeric(finish) and numeric(probe) else None
    pause_ms = 200 if record['scenario'] == 'source_pause' else 0
    canonical_ms = 1000 * fixture['samples'] / fixture['rate'] + pause_ms
    expected_probe = canonical_ms - 1000 * fixture['tail_guard_seconds']
    probe_offset = probe_elapsed - expected_probe if numeric(probe_elapsed) else None
    done, finished = event(record, 'producer_done_received'), event(record, 'finished')
    final = event(record, 'client_finished')
    done_at = record.get('producer_done_received_ms')
    done_received = done is not None and numeric(done_at)
    finish_at = (finished or {}).get('performance_ms')
    final_at = (final or {}).get('performance_ms')
    elapsed_finish = ratio(finish - first, rate, 1000) if numeric(finish) and numeric(first) else None
    return {
        'expected_source_samples': expected, 'produced_samples': server.get('produced_samples'),
        'source_supply_complete': server.get('produced_samples') == expected,
        'server_source_exhausted_event': event(server, 'source_exhausted') is not None,
        'producer_done_received': done_received,
        'producer_done_before_client_finished': done_received and numeric(final_at) and done_at <= final_at,
        'producer_done_to_worklet_finished_ms': finish_at - done_at
            if numeric(finish_at) and numeric(done_at) else None,
        'producer_done_to_client_finished_ms': final_at - done_at
            if numeric(final_at) and numeric(done_at) else None,
        'ws_received_samples': record.get('received_samples') if record['transport'] == 'ws' else None,
        'ws_consumed_samples': playback.get('consumed') if record['transport'] == 'ws' else None,
        'ws_all_samples_consumed': record.get('received_samples') == playback.get('consumed') == expected
            if record['transport'] == 'ws' else None,
        'rtc_bit_exact_source_ack': None,
        'probe_elapsed_from_first_render_ms': probe_elapsed,
        'expected_probe_elapsed_ms': expected_probe,
        'probe_offset_ms': probe_offset,
        'probe_tolerance_ms': PROBE_TOLERANCE_MS,
        'probe_near_expected_end': abs(probe_offset) <= PROBE_TOLERANCE_MS
            if numeric(probe_offset) else None,
        'worklet_guard_ms': guard,
        'worklet_finish_vs_canonical_end_ms': elapsed_finish - canonical_ms
            if numeric(elapsed_finish) else None,
    }


def validate_final(document, servers):
    """No aggregation is allowed before every final-run integrity barrier passes."""
    require(document.get('mode') == 'formal', 'not a formal browser batch')
    require(document.get('endedAt'), 'waiting for endedAt')
    require(document.get('headless') is True and str(document.get('browserVersion', '')).startswith('155.'),
            'expected headless Chrome 155')
    require(document.get('repeat') == 3, 'expected three repeats')
    records = document.get('records') or []
    require(len(records) == 24, f'waiting for 24 records: {len(records)}/24')
    expected = set(itertools.product(SCENARIOS, TRANSPORTS, FIXTURES, range(3)))
    keys = [(r.get('scenario'), r.get('transport'), r.get('fixture_id'), r.get('repeat')) for r in records]
    require(set(keys) == expected and len(set(keys)) == 24, 'missing/duplicate formal factorial cells')
    ids = [r.get('run_id') for r in records]
    require(len(set(ids)) == 24 and all(isinstance(x, str) and x.startswith('formal-') for x in ids),
            'invalid/duplicate formal run IDs')
    manifest = {f['id']: f for f in document['fixtureManifest']['fixtures']}
    require(set(manifest) == set(FIXTURES), 'fixture manifest mismatch')
    for r in records:
        run = r['run_id']
        require(r.get('outcome') == 'complete' and not r.get('error'), f'{run}: not complete')
        require(r.get('saved') is True, f'{run}: client record not saved')
        require(r['fixture'] == manifest[r['fixture_id']], f'{run}: fixture metadata mismatch')
        require(r.get('context_rate') == r['fixture'].get('rate') == 48000,
                f'{run}: expected 48kHz context and source')
        a, b = r.get('first_render_notification_performance_ms'), r.get('media_start_performance_ms')
        value = r.get('start_to_first_render_ms')
        require(numeric(a) and numeric(b) and numeric(value) and value >= 0
                and math.isclose(a - b, value, abs_tol=1e-6), f'{run}: primary timing mismatch')
        require(numeric(r.get('connect_ms')) and r['connect_ms'] >= 80, f'{run}: invalid connect_ms')
        integrity = sample_integrity(r, servers[run])
        require(integrity['source_supply_complete'], f'{run}: source supply incomplete')
        if r['transport'] == 'ws':
            require(integrity['ws_all_samples_consumed'], f'{run}: WS sample counts incomplete')
            underrun_samples = r.get('playback', {}).get('underrun_samples')
            require(numeric(underrun_samples) and numeric(r.get('ws_underrun_ms'))
                    and math.isclose(r['ws_underrun_ms'], 1000 * underrun_samples / r['context_rate'], abs_tol=1e-6),
                    f'{run}: WS underrun sample/time mismatch')
        else:
            require(integrity['producer_done_received'], f'{run}: RTC producer_done not received')
            require(integrity['producer_done_before_client_finished'], f'{run}: RTC control barrier failed')
            require(integrity['probe_near_expected_end'], f'{run}: RTC probe implausibly early/late')
            require(numeric(integrity['worklet_guard_ms']) and 250 <= integrity['worklet_guard_ms'] <= 260,
                    f'{run}: RTC guard outside 250–260ms')
    return records


def analyze_formal(document, servers):
    records = validate_final(document, servers)
    points, groups = [], []
    for r in records:
        points.append({k: r.get(k) for k in
                       ('run_id', 'scenario', 'transport', 'fixture_id', 'repeat', 'outcome',
                        'connect_ms', 'start_to_first_render_ms', 'ws_underrun_ms')})
        point = points[-1]
        point['integrity'] = sample_integrity(r, servers[r['run_id']])
        point['rtc'] = rtc_stats(r) if r['transport'] == 'rtc' else None
    for scenario, transport, fixture in itertools.product(SCENARIOS, TRANSPORTS, FIXTURES):
        rows = sorted((p for p in points if (p['scenario'], p['transport'], p['fixture_id']) ==
                       (scenario, transport, fixture)), key=lambda p: p['repeat'])
        group = {'scenario': scenario, 'transport': transport, 'fixture_id': fixture,
                 'n_expected': 3, 'n': len(rows), 'n_complete': len(rows), 'n_failed': 0,
                 'repeat_indices': [p['repeat'] for p in rows], 'failures': [],
                 'run_ids': [p['run_id'] for p in rows]}
        group['metrics'] = {key: distribution(p[key] for p in rows) for key in
                            ('start_to_first_render_ms', 'connect_ms', 'ws_underrun_ms')}
        group['rtc_delta'] = {key: distribution(p['rtc']['delta'][key] for p in rows)
                              for key in (*COUNTERS, 'jitter_buffer_mean_delay_ms',
                                          'packet_loss_fraction', 'packet_loss_denominator')} if transport == 'rtc' else None
        group['rtc_end_snapshot'] = {key: distribution(p['rtc']['end'][key] for p in rows)
                                     for key in COUNTERS} if transport == 'rtc' else None
        groups.append(group)
    pooled = {}
    for transport in TRANSPORTS:
        rows = [p for p in points if p['scenario'] == 'baseline' and p['transport'] == transport]
        pooled[transport] = {
            'n': len(rows), 'n_fixtures': 2, 'repeats_per_fixture': 3, 'n_failed': 0,
            'note': 'Two fixed fixtures × three repeated runs; six observations, not six independent fixtures.',
            'start_to_first_render_ms': distribution(p['start_to_first_render_ms'] for p in rows),
            'connect_ms': distribution(p['connect_ms'] for p in rows),
        }
    rtc = [p for p in points if p['transport'] == 'rtc']
    ws = [p for p in points if p['transport'] == 'ws']
    paths = Counter()  # Omit per-run pair IDs when counting observed path types.
    for p in rtc:
        path = {k: v for k, v in p['rtc']['path'].items() if k != 'candidate_pair_id'}
        paths[json.dumps(path, sort_keys=True)] += 1
    return {
        'n_expected': 24, 'n': 24, 'n_complete': 24, 'n_failed': 0,
        'groups': groups, 'baseline_pooled_by_transport': pooled, 'records': points,
        'rtc_paths': [{'n': count, **json.loads(path)} for path, count in paths.items()],
        'integrity': {
            'source_supply_complete_n': sum(p['integrity']['source_supply_complete'] for p in points),
            'ws_n': len(ws), 'ws_all_samples_consumed_n': sum(p['integrity']['ws_all_samples_consumed'] for p in ws),
            'rtc_n': len(rtc), 'rtc_producer_done_received_n': sum(p['integrity']['producer_done_received'] for p in rtc),
            'rtc_probe_near_expected_end_n': sum(p['integrity']['probe_near_expected_end'] for p in rtc),
            'rtc_missing_inbound_start_n': sum(not p['rtc']['inbound_start_present'] for p in rtc),
            'rtc_source_bit_exact_playback_proven': False,
        },
    }


def analyze_sessions(summary, audit):
    checks = summary['checks']
    counts = dict(Counter(c['scenario'] for c in checks))
    require(summary.get('passed') is True and all(c.get('passed') is True for c in checks),
            'session HTTP/WS checks failed')
    require(audit.get('passed') is True and audit.get('assertions') == len(checks)
            and audit.get('scenario_checks') == counts, 'session audit/check count mismatch')
    require(summary.get('audio_played') is False and
            summary.get('ack_source') == 'python_synthetic_control_only', 'unexpected Python ACK provenance')
    require(audit['forced_played_samples'] + audit['forced_unplayed_samples'] == summary['audio']['total_samples'],
            'forced-drain sample accounting mismatch')
    return {'passed': True, 'n_checks': len(checks), 'n_failed': 0,
            'scenario_checks': counts, 'ack_source': summary['ack_source'],
            'audio_played': False, 'browser_playback_latency': None,
            'audio': summary['audio'], 'audit': audit,
            'cleanup': summary.get('cleanup'),
            'scope': 'Python synthetic control and session state transitions; not real audio rendering.'}


def analyze_drain(record, verification):
    producer = event(record, 'producer_done_observed')
    initial = event(record, 'initial_buffer_released')
    finished = next((e for e in record['events'] if e.get('event') == 'worklet'
                     and e.get('observation', {}).get('type') == 'finished'), None)
    require(producer is not None and initial is not None and finished is not None, 'missing browser drain events')
    total = finished['observation']['consumed']
    observed_unrendered = total - producer['played_samples_cumulative']
    duration = finished['performance_ms'] - producer['performance_ms']
    require(total == verification.get('rendered_samples') == record['played']['played_samples_cumulative'],
            'browser drain consumed-sample mismatch')
    require(observed_unrendered == verification.get('producer_unrendered_samples'), 'drain report count mismatch')
    require(math.isclose(duration, verification['producer_to_finished_ms'], abs_tol=1e-6), 'drain timing mismatch')
    require(record['played']['ack_source'] == verification['ack_source'] == 'audio_worklet_consumed',
            'browser drain ACK is not worklet consumption')
    require(record['done']['terminal']['worker']['status'] == verification['worker_status'] == 'drained',
            'browser worker did not drain')
    require(record.get('acoustic_loopback') is False and verification.get('acoustic_loopback') is False,
            'unexpected acoustic measurement provenance')
    return {'n': 1, 'initial_buffer_ms': initial['initial_buffer_ms'],
            'initial_buffer_samples': initial['buffered_samples'], 'rendered_samples': total,
            'producer_done_observed_performance_ms': producer['performance_ms'],
            'worklet_finished_notification_performance_ms': finished['performance_ms'],
            'producer_to_finished_ms': duration,
            'latest_report_unrendered_samples_at_producer_observation': observed_unrendered,
            'latest_report_consumed_samples_at_producer_observation': producer['played_samples_cumulative'],
            'unrendered_count_is_exact_instantaneous_queue': False,
            'ack_source': verification['ack_source'], 'worker_status': verification['worker_status'],
            'acoustic_loopback': False,
            'scope': 'Same-browser performance clock: producer_done observed → worklet finished notification; includes message dispatch.'}


def analyze_remote(document):
    require(document.get('endedAt') and document.get('mode') == 'connectivity', 'remote connectivity batch unfinished')
    rows = document['records']
    require(len(rows) == 2 and Counter(r['transport'] for r in rows) == {'ws': 1, 'rtc': 1},
            'unexpected remote connectivity matrix')
    return {'scope': 'Remote connectivity only: WS via SSH forwarding; not a fair speed comparison with local UDP.',
            'mode': document['mode'], 'startedAt': document['startedAt'], 'endedAt': document['endedAt'],
            'n': len(rows), 'n_complete': sum(r.get('outcome') == 'complete' for r in rows),
            'n_failed': sum(r.get('outcome') != 'complete' for r in rows),
            'records': [{k: r.get(k) for k in ('run_id', 'transport', 'outcome', 'error',
                         'connect_ms', 'start_to_first_render_ms', 'received_samples', 'rtc_events')}
                        for r in rows], 'included_in_formal_statistics': False}


def build_summary(document, servers, session, audit, drain, verification, remote):
    formal = analyze_formal(document, servers)
    sessions = analyze_sessions(session, audit)
    browser_drain = analyze_drain(drain, verification)
    short = next(f for f in document['fixtureManifest']['fixtures'] if f['id'] == 'short')
    require(session['audio']['pcm_sha256'] == short['pcm_sha256'] and
            session['audio']['total_samples'] == browser_drain['rendered_samples'] == short['samples'],
            'session/browser short fixture mismatch')
    return {
        'schema_version': 'exp15.v2', 'generated_at': datetime.now(timezone.utc).isoformat(),
        'config': {'headlessChrome155': True, 'browser_version': document['browserVersion'],
                   'headless': document['headless'], 'startedAt': document['startedAt'],
                   'endedAt': document['endedAt'], 'mode': document['mode'],
                   'fixtures': document['fixtureManifest']['fixtures'], 'repeats_per_cell': 3,
                   'source_pause_ms': 200, 'new_gpu_inferences': 0,
                   'primary_input': 'phase4/results/exp15/browser-formal-v2/records.json'},
        'metric_definitions': {
            'start_to_first_render_ms': 'performance(first non-silent AudioWorklet notification received on main thread) minus performance(media start). Includes message dispatch; boundary probe, not acoustic first sound or a full model turn.',
            'connect_ms': 'Signaling, connection establishment and player preparation, including 80ms warmup; not pure handshake latency.',
            'excluded_primary_metrics': ['connect_to_first_render_ms', 'audio_clock*'],
            'source_pause': 'Source supply pauses for 200ms after 50 × 20ms frames; no network packet loss injection.',
            'ws_underrun_ms': 'Worklet empty-queue samples after playback starts and before expected source consumption / 48 samples per ms.',
            'rtc_delta': 'Matched inbound-rtp end minus start counters. Missing field or missing start stream => null; never assume zero.',
            'jitter_buffer_mean_delay_ms': '1000 × delta(jitterBufferDelay seconds) / delta(jitterBufferEmittedCount); missing or zero denominator => null.',
            'packet_loss_fraction': 'delta(packetsLost) / (delta(packetsReceived) + delta(packetsLost)); missing/zero denominator => null. Signed lost-counter corrections are retained.',
            'rtc_end_snapshot': 'Diagnostic cumulative end values, not an interval delta and not comparable to WS empty-queue duration.',
            'rtc_complete': 'End-probe detection plus >=250ms guard AND client receives DataChannel producer_done; no bit-exact source sample ACK.',
            'probe_plausibility': 'AudioContext frames used only for end-probe diagnostics. Expected offset = fixture samples/rate minus 300ms tail + optional 200ms pause; tolerance ±250ms. A plausibility screen, not proof against all false positives.',
            'rtc_tail': '300ms canonical zero tail versus 250ms guard may finish roughly 50ms before canonical tail end; codec time scaling and block alignment also affect timing.',
            'ws_complete': 'received_samples == worklet consumed == fixture.samples; no acoustic loopback.',
        },
        'formal': formal, 'sessions': sessions, 'browser_drain': browser_drain,
        'remote_connectivity': analyze_remote(remote),
        'exclusions': {'pilot_and_failed_starts': 'No globbing or directory merging; only the named v2 final input.',
                       'browser_formal_v1': 'Diagnostic only: full RTC source supply but two source_pause/short client producer_done controls missing before close. Excluded from all final p50 values.'},
        'data_issues': ([{'code': 'rtc_inbound_start_missing',
                         'n': formal['integrity']['rtc_missing_inbound_start_n'],
                         'effect': 'RTC interval counters and derived delay/loss ratios stay null. End snapshots are separately labeled diagnostics.'}]
                        if formal['integrity']['rtc_missing_inbound_start_n'] else []),
    }


def load_final():
    document = read_json(FINAL_RECORDS)
    servers = {r['run_id']: read_json(RESULTS / 'media-server-formal' / f'server-{r["run_id"]}.json')
               for r in document.get('records', [])}
    return document, servers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        document, servers = load_final()
        validate_final(document, servers)
        if args.check:
            print('READY: v2 ended; 24/24 complete; source counts full; RTC probe and producer_done barriers passed')
            return 0
        paths = {
            'formal_records': FINAL_RECORDS,
            'session_checks': RESULTS / 'sessions/http-ws-final/summary.json',
            'session_audit': RESULTS / 'sessions/evidence-audit.json',
            'browser_drain': RESULTS / 'sessions/browser-playback/record.json',
            'browser_drain_verification': RESULTS / 'sessions/browser-playback/verification.json',
            'remote_connectivity': RESULTS / 'browser-remote-v2/records.json',
        }
        summary = build_summary(document, servers, *(read_json(paths[k]) for k in
            ('session_checks', 'session_audit', 'browser_drain', 'browser_drain_verification', 'remote_connectivity')))
        summary['provenance'] = {k: provenance(path) for k, path in paths.items()}
        summary['provenance']['media_servers'] = [
            provenance(RESULTS / 'media-server-formal' / f'server-{r["run_id"]}.json')
            for r in document['records']]
        # A refused/in-progress run must never replace a previously validated summary.
        FINAL_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(FINAL_OUTPUT)
        return 0
    except (EvidenceError, FileNotFoundError, json.JSONDecodeError, KeyError) as error:
        print(f'NOT READY: {error}; final summary not written')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
