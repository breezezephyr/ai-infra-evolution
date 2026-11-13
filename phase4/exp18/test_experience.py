"""Behavioral checks for the offline experience ledger (no services or GPU)."""
import json
from pathlib import Path
import tempfile
import unittest

try:
    from . import experience as ex
except ImportError:
    try:
        import experience as ex
    except ImportError:
        ex = None


CASE = {'id': 'short', 'sample_rate': 1000, 'samples': 200,
        'speech_intervals': [{'start': 0, 'end': 100}], 'sha256': 'c' * 64}


def turn(latency=700, *, early=False, reason='stop', identity='one'):
    return {'id': identity, 'case_id': 'short', 'mode': 'A', 'repeat': 0,
            'warmup': False, 'endpoint_early': False,  # Deliberately untrusted.
            'input_start_ns': 0, 'reference_input_end_ns': 100_000_000,
            'client_clock_domain': 'client_monotonic',
            'first_pcm_received_ns': int((latency + 100) * 1e6),
            'input_pcm_sha256': 'a' * 64, 'output_pcm_sha256': 'b' * 64,
            'input_sha256': 'c' * 64, 'output_samples': 10,
            'terminal': {'type': 'terminal', 'finish_reason': reason,
                         'session_id': identity, 'input_pcm_sha256': 'a' * 64,
                         'output_pcm_sha256': 'b' * 64, 'output_samples': 10,
                         'state': {'error': None},
                         'events': [{'event': 'endpoint_confirmed',
                                     'sample_offset': 90 if early else 110,
                                     'session_id': identity}]}}


def browser():
    return {'id': 'browser', 'mode': 'A', 'source': 'browser_web_audio',
            'terminal': {'type': 'terminal', 'finish_reason': 'stop',
                         'output_samples': 10, 'state': {},
                         'events': [{'event': 'endpoint_confirmed', 'sample_offset': 160}]},
            'timestamps': {'clock_domain': 'browser_performance', 'unit': 'ms',
                           'input_reference_end_perf_ms': 110,
                           'first_pcm_received_perf_ms': 120,
                           'first_non_silent_render_perf_ms': 200},
            'evidence': {'input_complete': True, 'server_terminal_received': True,
                         'output_samples_received': 10, 'output_samples_consumed': 10,
                         'playback_drained': True,
                         'input_reference_mapping': {
                             'clock_domain': 'browser_performance',
                             'method': 'actual_frame_send_plus_sample_offset',
                             'reference_sample': 160, 'frame_sample_offset': 0,
                             'frame_count': 320, 'frame_send_performance_ms': 100,
                             'performance_ms': 110},
                         'input_frame_sends': [{'sample_offset': 0, 'count': 320,
                                                'performance_ms': 100}],
                         'clock_anchors': [{'performance_before_ms': 149,
                                            'performance_after_ms': 151, 'context_time_s': 1}],
                         'playback_events': [{'type': 'first_non_silent_render',
                                              'context_time_s': 1.05, 'anchor_index': 0,
                                              'performance_ms': 200,
                                              'observed_performance_ms': 217}],
                         'get_output_timestamp_supported': False}}


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ex, 'experience extractor has not been implemented')

    def test_early_stop_is_failure_and_cannot_win_latency_or_threshold(self):
        rows = [turn(700), turn(-50, early=True, identity='early'),
                turn(10, reason='error', identity='error')]
        points = [ex.formal_turn(r, CASE) for r in rows]
        result = ex.summarize_turns(points)
        self.assertEqual(result['counts']['stop'], 2)
        self.assertEqual(result['counts']['early'], 1)
        self.assertEqual(result['counts']['success'], 1)
        self.assertEqual(result['first_pcm_ms']['p50'], 700)
        self.assertEqual(result['first_pcm_ms']['failures'], 2)
        self.assertEqual(result['candidate_800ms']['eligible'], 3)
        self.assertEqual(result['candidate_800ms']['passed'], 1)
        self.assertEqual(result['candidate_800ms']['failed'], 2)

    def test_missing_timestamp_is_unknown_in_full_threshold_denominator(self):
        row = turn()
        del row['first_pcm_received_ns']
        result = ex.summarize_turns([ex.formal_turn(row, CASE)])
        self.assertIsNone(result['first_pcm_ms']['p50'])
        self.assertEqual(result['first_pcm_ms']['unknown'], 1)
        self.assertEqual(result['candidate_800ms']['eligible'], 1)
        self.assertEqual(result['candidate_800ms']['unknown'], 1)
        self.assertIsNone(result['candidate_800ms']['all_observations_pass'])

    def test_missing_endpoint_is_unknown_even_if_stored_early_is_false(self):
        row = turn()
        row['terminal']['events'] = []
        point = ex.formal_turn(row, CASE)
        self.assertIsNone(point['endpoint_complete'])
        self.assertIsNone(point['success'])
        self.assertEqual(ex.summarize_turns([point])['candidate_800ms']['unknown'], 1)

    def test_integrity_mismatch_fails_and_missing_hash_is_unknown(self):
        bad, missing = turn(), turn(identity='missing')
        bad['terminal']['output_pcm_sha256'] = 'd' * 64
        del missing['terminal']['output_pcm_sha256']
        result = ex.summarize_turns([ex.formal_turn(r, CASE) for r in [bad, missing]])
        self.assertEqual(result['first_pcm_ms']['measured'], 0)
        self.assertEqual(result['candidate_800ms']['failed'], 1)
        self.assertEqual(result['candidate_800ms']['unknown'], 1)

    def test_invalid_equal_hashes_cannot_prove_integrity(self):
        row = turn()
        row['output_pcm_sha256'] = row['terminal']['output_pcm_sha256'] = 'invalid'
        self.assertIsNone(ex.formal_turn(row, CASE)['success'])

    def test_hostclock_is_rejected_without_falling_back_to_stored_delta(self):
        row = turn()
        row['client_clock_domain'] = 'hostclock'
        row['replay_end_to_first_pcm_ms'] = 0
        point = ex.formal_turn(row, CASE)
        self.assertIsNone(point['first_pcm_ms'])
        self.assertEqual(ex.summarize_turns([point])['candidate_800ms']['unknown'], 1)

    def test_quantiles_use_whole_observations_not_sum_of_stage_percentiles(self):
        # Two anticorrelated stages total 100 in both turns; summed p95 is 190.
        rows = [turn(100, identity='a'), turn(100, identity='b')]
        rows[0]['stages'] = [0, 100]
        rows[1]['stages'] = [100, 0]
        result = ex.summarize_turns([ex.formal_turn(r, CASE) for r in rows])
        self.assertEqual(result['first_pcm_ms']['p95'], 100)
        self.assertEqual(ex.distribution([0, 100])['p95'], 95)
        self.assertIsNone(ex.distribution([None])['p50'])

    def test_browser_notification_and_calibrated_render_are_distinct(self):
        point = ex.browser_turn(browser())
        self.assertAlmostEqual(point['first_non_silent_render_ms'], 90)
        self.assertEqual(point['first_render_notification_ms'], 107)
        self.assertIsNone(point['acoustic_first_sound_ms'])

    def test_browser_clock_mismatch_rejects_latency(self):
        row = browser()
        row['evidence']['input_reference_mapping']['clock_domain'] = 'hostclock'
        row['latencies_ms'] = {'first_non_silent_render': 0}
        point = ex.browser_turn(row)
        self.assertIsNone(point['first_pcm_ms'])
        self.assertIsNone(point['first_non_silent_render_ms'])
        self.assertIsNone(point['first_render_notification_ms'])

    def test_browser_missing_notification_does_not_become_zero(self):
        row = browser()
        del row['evidence']['playback_events'][0]['observed_performance_ms']
        point = ex.browser_turn(row)
        self.assertIsNone(point['first_render_notification_ms'])
        self.assertAlmostEqual(point['first_non_silent_render_ms'], 90)

    def test_browser_notification_with_explicit_hostclock_is_rejected(self):
        row = browser()
        row['evidence']['playback_events'][0]['clock_domain'] = 'hostclock'
        self.assertIsNone(ex.browser_turn(row)['first_render_notification_ms'])

    def test_rtc_end_snapshot_never_becomes_interval_without_matching_start(self):
        row = {'rtc_stats_end': [{'type': 'inbound-rtp', 'kind': 'audio', 'id': 'stream',
                                 'concealedSamples': 120, 'packetsReceived': 5}]}
        stats = ex.rtc_counters(row)
        self.assertEqual(stats['end']['concealedSamples'], 120)
        self.assertIsNone(stats['delta']['concealedSamples'])
        row['rtc_stats_start'] = [{'type': 'inbound-rtp', 'kind': 'audio', 'id': 'other',
                                  'concealedSamples': 10}]
        self.assertIsNone(ex.rtc_counters(row)['delta']['concealedSamples'])
        row['rtc_stats_start'][0]['id'] = 'stream'
        self.assertEqual(ex.rtc_counters(row)['delta']['concealedSamples'], 110)

    def test_exp15_media_clock_rejects_hostclock(self):
        row = {'run_id': 'x', 'transport': 'ws', 'clock_domain': 'hostclock',
               'media_start_performance_ms': 10, 'first_render_notification_performance_ms': 20}
        point = ex.media_turn(row, {})
        self.assertIsNone(point['start_to_first_render_ms'])

    def test_media_failure_cannot_lower_render_latency_distribution(self):
        points = [{'success': True, 'start_to_first_render_ms': 50},
                  {'success': False, 'start_to_first_render_ms': 1},
                  {'success': True, 'start_to_first_render_ms': None}]
        result = ex.signal(points, 'start_to_first_render_ms', 'browser_performance', 'render')
        self.assertEqual((result['eligible'], result['measured'], result['failures'], result['unknown']),
                         (3, 1, 1, 1))
        self.assertEqual(result['p50'], 50)

    def test_extract_uses_only_named_final_raw_and_has_provenance(self):
        root = Path(__file__).resolve().parents[1]
        result = ex.extract(root)
        formal = result['exp14']['formal']
        self.assertEqual((formal['n'], formal['n_warmup']), (108, 3))
        self.assertEqual(formal['counts']['stop'], 108)
        for mode, early, success, gate in [('A', 6, 30, 0), ('B', 9, 27, 6), ('C', 9, 27, 6)]:
            group = formal['by_mode'][mode]
            self.assertEqual((group['n'], group['counts']['early'], group['counts']['success']),
                             (36, early, success))
            self.assertEqual(group['candidate_800ms']['eligible'], 36)
            self.assertEqual(group['candidate_800ms']['passed'], gate)
        self.assertEqual(result['exp14']['browser']['n'], 3)
        media = result['exp15']['media']
        self.assertEqual(media['n'], 24)
        for path in ['ws', 'rtc']:
            for scene in ['baseline', 'source_pause']:
                self.assertEqual(media['groups'][f'{path}/{scene}']['n'], 6)
        self.assertEqual(media['groups']['rtc/baseline']['rtc_concealed_delta']['unknown'], 6)
        drain = result['exp15']['drain']
        self.assertEqual(drain['n'], 1)
        self.assertAlmostEqual(drain['producer_done_to_finished_ms']['p50'], 654.7, places=5)
        self.assertEqual(drain['source_samples'], 149760)
        self.assertEqual(drain['latest_report_unrendered_samples'], 35456)
        self.assertEqual(result['exp15']['control']['forced'][0]['unacknowledged_samples'], 125760)
        for source in result['sources']:
            self.assertEqual(len(source['sha256']), 64)
            self.assertNotIn('summary.json', source['path'])
        json.dumps(result, allow_nan=False)

    def test_final_selection_does_not_merge_pilot_or_read_summary(self):
        # Removing all old summaries must leave extraction possible; only final paths exist.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for relative in ['exp14/audio/manifest.json', 'exp14/run.py', 'exp14/playback.js',
                             'exp14/prepare_audio.py',
                             'exp15/client.js', 'exp15/session-client.js', 'exp15/server.py',
                             'exp15/session_http.py', 'exp14/analyze.py', 'exp15/analyze.py']:
                dest = target / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((root / relative).read_bytes())
            import shutil
            for relative in ['results/exp14/live-final-v1', 'results/exp14/server-eof-fixed',
                             'results/exp15/browser-formal-v2', 'results/exp15/media-server-formal',
                             'results/exp15/sessions/browser-playback',
                             'results/exp15/sessions/http-ws-final']:
                shutil.copytree(root / relative, target / relative,
                                ignore=shutil.ignore_patterns('*.wav', '*.pcm', '*.png', '*.log',
                                                              'summary.json', 'verification.json'))
            pilot = target / 'results/exp15/browser-pilot/records.json'
            pilot.parent.mkdir(parents=True)
            pilot.write_text('{invalid pilot')
            self.assertEqual(ex.extract(target)['exp15']['media']['n'], 24)
            formal_path = target / 'results/exp14/live-final-v1/records.jsonl'
            rows = [json.loads(s) for s in formal_path.read_text().splitlines()]
            rows = [r for r in rows if r['id'] != 'live-final-v1-short_01-r0-A-4']
            formal_path.write_text('\n'.join(json.dumps(r) for r in rows))
            formal = ex.extract(target)['exp14']['formal']
            self.assertEqual(formal['n_raw_formal'], 107)
            self.assertEqual(formal['by_mode']['A']['candidate_800ms']['eligible'], 36)
            self.assertEqual(formal['by_mode']['A']['candidate_800ms']['unknown'], 1)


if __name__ == '__main__':
    unittest.main()
