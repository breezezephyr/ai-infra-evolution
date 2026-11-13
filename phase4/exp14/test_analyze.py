"""Offline schema/measurement boundaries; no GPU, network or installation needed."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def event(name, ms, domain='server_monotonic', **fields):
    return {'event': name, 'clock_domain': domain,
            'monotonic_ns': round(ms * 1_000_000), **fields}


def turn(identity='one', mode='A', case='q1', latency=100):
    """Hand-timed example of run.py/server.py/pipeline.py's actual contract."""
    return {
        'id': identity, 'mode': mode, 'case_id': case, 'repeat': 0,
        'warmup': False, 'kind': 'paced_input_capture_only',
        'reference_text': '你好，Ａ！', 'input_sha256': 'a' * 64,
        'client_clock_domain': 'client_monotonic',
        'reference_input_end_ns': 1_000_000_000,
        'first_pcm_received_ns': 1_000_000_000 + round(latency * 1_000_000),
        'first_non_silent_received_ns': None,
        'replay_end_to_first_pcm_ms': latency,
        'first_non_silent_render_ms': None,
        'device_output_estimate_ms': None, 'acoustic_first_sound_ms': None,
        'endpoint_early': False, 'output_samples': 480, 'output_frames': [],
        'output_pcm_sha256': 'b' * 64,
        'terminal': {
            'type': 'terminal', 'finish_reason': 'stop', 'input_complete': True,
            'input_pcm_sha256': 'c' * 64, 'output_pcm_sha256': 'b' * 64,
            'output_samples': 480,
            'state': {'asr_text': '你好a', 'text': '好的。',
                      'llm': {'thread_stopped': True},
                      'tts_worker_returned': True, 'tts_thread_stopped': True},
            'events': [
                event('input_frame_received', 5, sample_offset=0, samples=512),
                event('endpoint_confirmed', 15, last_speech_sample=512),
                event('asr_start', 20), event('asr_end', 40, text='你好a'),
                event('llm_start', 40), event('first_text', 50),
                event('tts_text_submitted', 55), event('tts_start', 60),
                event('first_pcm', 80), event('first_audio_sent', 85),
                event('tts_part_end', 100), event('llm_end', 110),
                event('workers_joined', 115, llm=True, tts=True)]}}


def browser_turn():
    """playback.js export: sample -> performance mapping and render anchor."""
    return {
        'id': 'browser-1', 'case_id': 'q1', 'mode': 'A', 'source': 'browser_web_audio',
        'timestamps': {'clock_domain': 'browser_performance', 'unit': 'ms',
                       'input_reference_end_perf_ms': 1020, 'first_pcm_received_perf_ms': 1120,
                       'first_non_silent_render_perf_ms': 1220,
                       'first_non_silent_device_output_estimate_perf_ms': 1230,
                       'acoustic_first_sound_perf_ms': None},
        'evidence': {
            'input_complete': True, 'server_terminal_received': True,
            'output_samples_received': 480, 'output_samples_consumed': 480,
            'playback_drained': True, 'underrun_rate': 24000,
            'input_reference_mapping': {'reference_sample': 320, 'frame_sample_offset': 0,
                                        'frame_count': 320, 'frame_send_performance_ms': 1000,
                                        'performance_ms': 1020, 'clock_domain': 'browser_performance',
                                        'method': 'actual_frame_send_plus_sample_offset'},
            'input_frame_sends': [{'sample_offset': 0, 'count': 320, 'performance_ms': 1000}],
            'clock_anchors': [{'context_time_s': 1.0, 'performance_before_ms': 1219,
                               'performance_after_ms': 1221}],
            'playback_events': [{'type': 'first_non_silent_render', 'context_time_s': 1.0,
                                 'performance_ms': 1220, 'source_sample': 12, 'anchor_index': 0},
                                {'type': 'playback_progress', 'consumed_samples': 480}],
            'get_output_timestamp_supported': True,
            'first_sound_device_anchor_index': 0,
            'output_timestamp_anchors': [{'contextTime': .99, 'performanceTime': 1220}]},
        'underrun_samples': 240, 'underrun_events': 2,
        'terminal': {'type': 'terminal', 'finish_reason': 'stop', 'output_samples': 480,
                     'events': [event('endpoint_confirmed', 5, sample_offset=640)]}}


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tempfile.TemporaryDirectory(prefix='exp14-mpl-')
        cls.old_mpl_config = os.environ.get('MPLCONFIGDIR')
        os.environ['MPLCONFIGDIR'] = cls.config.name
        cls.module = None
        path = HERE / 'analyze.py'
        if path.exists():
            spec = importlib.util.spec_from_file_location('exp14_analyze', path)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.old_mpl_config is None:
            os.environ.pop('MPLCONFIGDIR', None)
        else:
            os.environ['MPLCONFIGDIR'] = cls.old_mpl_config
        cls.config.cleanup()

    def analyze(self, rows, **kwargs):
        self.assertIsNotNone(self.module, 'exp14 analysis has not been implemented')
        return self.module.analyze_records(rows, **kwargs)

    def test_no_data_has_explicit_zero_denominators_and_null_measurements(self):
        result = self.analyze([])
        for mode in 'ABC':
            group = result['modes'][mode]
            self.assertEqual(group['n'], 0)
            self.assertEqual(group['n_independent_cases'], 0)
            self.assertEqual(group['replay_end_to_first_pcm_ms'],
                             {'n': 0, 'p50': None, 'p95': None})
            self.assertIsNone(group['all_workers_joined'])
        self.assertEqual(result['browser']['n'], 0)
        self.assertEqual(result['components']['reports'], [])

    def test_early_errors_and_every_non_stop_terminal_stay_in_denominator(self):
        rows = [turn('ok1', latency=100), turn('ok2', latency=300),
                turn('early', latency=-200), turn('client', latency=1),
                turn('length', latency=2), turn('timeout', latency=3),
                turn('missing', latency=4), turn('server-error', latency=5)]
        rows[2]['endpoint_early'] = True
        rows[3]['client_error'] = 'disconnected'
        rows[4]['terminal']['finish_reason'] = 'length'
        rows[5]['terminal']['finish_reason'] = 'timeout'
        rows[6]['terminal'] = None
        rows[7]['terminal']['finish_reason'] = 'error'
        warm = turn('warm', latency=0)
        warm['warmup'] = True
        result = self.analyze(rows + [warm])
        group = result['modes']['A']
        self.assertEqual(group['n'], 8)
        self.assertEqual(group['n_warmup'], 1)
        self.assertEqual(group['counts'], {
            'success': 2, 'early': 1, 'early_unknown': 0, 'error': 2,
            'client_error': 1, 'length': 1, 'stop': 4,
            'non_stop': 4, 'missing_terminal': 1})
        self.assertEqual(group['replay_end_to_first_pcm_ms'],
                         {'n': 2, 'p50': 200.0, 'p95': 290.0})
        self.assertEqual(len(result['points']), 9)
        self.assertEqual(result['points'][2]['raw']['replay_end_to_first_pcm_ms'], -200)
        self.assertFalse(result['points'][2]['success'])

    def test_repeats_do_not_inflate_independent_cases_and_preserve_raw_points(self):
        rows = [turn('r0'), turn('r1'), turn('other', case='q2')]
        rows[1]['repeat'] = 1
        result = self.analyze(rows)
        group = result['modes']['A']
        self.assertEqual((group['n'], group['n_independent_cases'],
                          group['n_independent_reference_texts']), (3, 2, 1))
        self.assertEqual(group['by_case']['q1']['n'], 2)
        self.assertEqual(result['points'][1]['raw'], rows[1])
        self.assertEqual(group['cer']['n_independent_cases'], 2)

    def test_silent_pcm_and_missing_browser_fields_never_become_zero_sound(self):
        row = turn()
        row['terminal']['state']['first_non_silent_sample'] = None
        result = self.analyze([row], browser_records=[
            {'source': 'browser_web_audio', 'id': 'b1', 'mode': 'A',
             'unrecognized_future_field': 123}])
        point = result['points'][0]
        self.assertIsNone(point['first_non_silent_received_ms'])
        browser = result['browser']['points'][0]
        for key in ('first_non_silent_render_ms', 'device_output_estimate_ms',
                    'acoustic_first_sound_ms', 'underrun_count', 'underrun_duration_ms'):
            self.assertIsNone(browser[key])
        self.assertEqual(browser['raw']['unrecognized_future_field'], 123)
        self.assertEqual(result['browser']['modes']['A']['first_non_silent_render_ms']['n'], 0)

    def test_cross_clock_and_missing_domain_are_not_subtracted(self):
        row = turn()
        row['terminal']['events'][3]['clock_domain'] = 'browser_performance'
        row['client_clock_domain'] = 'server_monotonic'
        result = self.analyze([row])
        self.assertIsNone(result['points'][0]['server_stages_ms']['asr_ms'])
        self.assertIsNone(result['points'][0]['replay_end_to_first_pcm_ms'])
        self.assertTrue(result['points'][0]['timing_issues'])
        del row['terminal']['events'][3]['clock_domain']
        self.assertIsNone(self.analyze([row])['points'][0]['server_stages_ms']['asr_ms'])

    def test_server_stages_use_monotonic_ns_and_keep_overlapping_intervals(self):
        result = self.analyze([turn()])
        point = result['points'][0]
        stages = point['server_stages_ms']
        self.assertEqual(stages['endpoint_wait_ms'], 10)
        self.assertEqual(stages['asr_ms'], 20)
        self.assertEqual(stages['llm_first_text_ms'], 10)
        self.assertEqual(stages['llm_total_ms'], 70)
        self.assertEqual(stages['tts_first_pcm_ms'], 20)
        self.assertEqual(stages['endpoint_to_first_pcm_ms'], 65)
        self.assertEqual(stages['endpoint_to_first_audio_sent_ms'], 70)
        intervals = point['server_intervals']
        self.assertEqual([(i['stage'], i['start_ns'], i['end_ns']) for i in intervals],
                         [('asr', 20_000_000, 40_000_000),
                          ('llm', 40_000_000, 110_000_000),
                          ('tts', 60_000_000, 100_000_000)])
        self.assertNotIn('sum_of_stage_p50_ms', result['modes']['A'])

    def test_reversed_or_cross_turn_event_pair_is_invalid(self):
        row = turn()
        row['terminal']['events'][3]['monotonic_ns'] = 19_000_000
        self.assertIsNone(self.analyze([row])['points'][0]['server_stages_ms']['asr_ms'])
        row = turn()
        row['terminal']['turn_id'] = 1
        row['terminal']['events'][3]['turn_id'] = 2
        self.assertIsNone(self.analyze([row])['points'][0]['server_stages_ms']['asr_ms'])

    def test_cer_normalizes_nfkc_case_punctuation_and_whitespace_but_not_traditional(self):
        row = turn()
        self.assertEqual(self.analyze([row])['points'][0]['cer'], 0)
        row['reference_text'] = '台湾'
        row['terminal']['state']['asr_text'] = '臺灣'
        result = self.analyze([row])
        self.assertEqual(result['points'][0]['cer'], 1)
        self.assertIn('no traditional/simplified conversion', result['notes']['cer'])
        row['reference_text'] = ' ， '
        self.assertIsNone(self.analyze([row])['points'][0]['cer'])
        row['reference_text'] = '你好'
        del row['terminal']['state']['asr_text']
        self.assertIsNone(self.analyze([row])['points'][0]['cer'])

    def test_workers_are_real_join_evidence_and_empty_is_unknown(self):
        good, bad, missing = turn('ok'), turn('bad'), turn('missing')
        bad['terminal']['state']['llm']['thread_stopped'] = False
        missing['terminal']['state'] = {}
        missing['terminal']['events'] = []
        result = self.analyze([good, bad, missing])
        group = result['modes']['A']
        self.assertEqual(group['workers_joined'], {'true': 1, 'false': 1, 'unknown': 1})
        self.assertFalse(group['all_workers_joined'])
        self.assertIsNone(result['points'][2]['all_workers_joined'])

    def test_wav_hash_is_never_compared_with_pcm_and_mismatch_excludes_success(self):
        row = turn()
        point = self.analyze([row])['points'][0]
        self.assertIsNone(point['hash_alignment']['input_pcm']['match'])
        self.assertTrue(point['hash_alignment']['output_pcm']['match'])
        row['input_pcm_sha256'] = 'c' * 64
        self.assertTrue(self.analyze([row])['points'][0]['hash_alignment']['input_pcm']['match'])
        row['output_pcm_sha256'] = 'd' * 64
        result = self.analyze([row])
        self.assertFalse(result['points'][0]['success'])
        self.assertEqual(result['modes']['A']['hash_alignment']['output_pcm']['mismatch'], 1)
        self.assertIsNone(result['modes']['A']['replay_end_to_first_pcm_ms']['p50'])

    def test_missing_early_flag_cannot_certify_success_and_zero_latency_is_valid(self):
        row = turn(latency=0)
        self.assertEqual(self.analyze([row])['modes']['A']['replay_end_to_first_pcm_ms']['p50'], 0)
        del row['endpoint_early']
        result = self.analyze([row])
        self.assertFalse(result['points'][0]['success'])
        self.assertEqual(result['modes']['A']['counts']['early_unknown'], 1)

    def test_component_warmup_excluded_and_resident_kept_separate(self):
        standalone = {'kind': 'actual_cuda_component_smoke', 'component': 'asr',
                      'models': {'asr': {'device': 'cuda', 'compute_type': 'int8_float16'}},
                      'observed_peak_mib': 1000, 'records': [
                          {'warmup': True, 'asr': {'ms': 9000}},
                          {'warmup': False, 'asr': {'ms': 10}},
                          {'warmup': False, 'asr': {'ms': 30}}]}
        resident = copy.deepcopy(standalone)
        resident.update(component='resident', loaded_mib=3000)
        resident['records'][1]['asr']['ms'] = 100
        resident['records'][2]['asr']['ms'] = 300
        result = self.analyze([], component_documents=[standalone, resident])
        reports = result['components']['reports']
        self.assertEqual(reports[0]['timings']['asr_ms'], {'n': 2, 'p50': 20.0, 'p95': 29.0})
        self.assertEqual(reports[1]['timings']['asr_ms']['p50'], 200)
        self.assertEqual([r['scope'] for r in reports], ['independent', 'resident'])
        self.assertEqual(reports[1]['raw_metadata']['loaded_mib'], 3000)
        self.assertEqual(reports[0]['n_warmup'], 1)
        fake = copy.deepcopy(standalone)
        fake['kind'] = 'synthetic'
        self.assertEqual(self.analyze([], component_documents=[fake])['components']['reports'], [])

    def test_cli_uses_input_paths_and_records_source_hashes(self):
        self.assertIsNotNone(self.module, 'exp14 analysis has not been implemented')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records, output = root / 'records.jsonl', root / 'summary.json'
            records.write_text(json.dumps(turn(), ensure_ascii=False) + '\n')
            browser, components = root / 'browser', root / 'components'
            browser.mkdir()
            components.mkdir()
            (browser / 'one.json').write_text(json.dumps({'source': 'browser_web_audio', 'mode': 'B'}))
            (components / 'asr.json').write_text(json.dumps({
                'kind': 'actual_cuda_component_smoke', 'component': 'asr',
                'records': [], 'models': {'asr': {'device': 'cuda'}}}))
            command = [sys.executable, '-B', str(HERE / 'analyze.py'),
                       '--records', str(records), '--browser-dir', str(browser),
                       '--components', str(components), '--output', str(output)]
            proc = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(output.read_text())
            self.assertEqual((summary['n_records'], summary['browser']['n']), (1, 1))
            self.assertEqual(len(summary['sources']), 3)
            import hashlib
            self.assertEqual(summary['sources'][0]['sha256'],
                             hashlib.sha256(records.read_bytes()).hexdigest())
            records.write_text('{broken json}\n')
            proc = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('records.jsonl:1', proc.stderr)

    def test_payload_hash_counts_include_unknown_and_never_use_wav_container(self):
        good, bad, unknown = turn('good'), turn('bad'), turn('unknown')
        good['input_pcm_sha256'] = 'c' * 64
        bad['input_pcm_sha256'] = 'd' * 64
        result = self.analyze([good, bad, unknown])
        self.assertEqual(result['modes']['A']['hash_alignment']['input_pcm'],
                         {'checked': 2, 'match': 1, 'mismatch': 1, 'unknown': 1})
        self.assertFalse(result['points'][1]['success'])

    def test_pair_consistency_is_case_and_repeat_aligned_excludes_warmup(self):
        a0, b0, c0 = turn('a0'), turn('b0', mode='B'), turn('c0', mode='C')
        b0['terminal']['state']['asr_text'] = '你好a。'
        c0['terminal']['state']['asr_text'] = '你好a。'
        c0['terminal']['state']['text'] = '再见。'
        c0['output_samples'] = c0['terminal']['output_samples'] = 960
        a1, b1, c1 = turn('a1'), turn('b1', mode='B'), turn('c1', mode='C')
        for row in (a1, b1, c1):
            row['repeat'] = 1
        del b1['terminal']['state']['asr_text']
        del c1['terminal']['state']['text']
        warm = copy.deepcopy(a0)
        warm['warmup'] = True
        result = self.analyze([a0, b0, c0, a1, b1, c1, warm])
        self.assertIn('paired_consistency', result, 'paired measurement analysis is missing')
        pairs = result['paired_consistency']
        self.assertEqual(pairs['A/B']['n_pairs'], 2)
        self.assertEqual(pairs['A/B']['asr_text_equal'], {'true': 0, 'false': 1, 'unknown': 1})
        self.assertEqual(pairs['A/B']['answer_text_equal'], {'true': 2, 'false': 0, 'unknown': 0})
        self.assertEqual(pairs['B/C']['asr_text_equal'], {'true': 1, 'false': 0, 'unknown': 1})
        self.assertEqual(pairs['B/C']['answer_text_equal'], {'true': 0, 'false': 1, 'unknown': 1})
        self.assertEqual(pairs['B/C']['output_samples_equal'], {'true': 1, 'false': 1, 'unknown': 0})
        self.assertEqual(pairs['A/B']['points'][0]['case_id'], 'q1')
        self.assertEqual(pairs['A/B']['points'][0]['record_ids'], ['a0', 'b0'])

    def test_pair_missing_or_duplicate_modes_are_explicit_not_arbitrarily_picked(self):
        a, b = turn('a'), turn('b', mode='B')
        result = self.analyze([a, b, turn('duplicate', mode='B'), turn('other', case='q2')])
        self.assertIn('paired_consistency', result, 'paired measurement analysis is missing')
        ab = result['paired_consistency']['A/B']
        self.assertEqual((ab['n_keys'], ab['n_pairs'], ab['n_ambiguous'], ab['n_missing']), (2, 0, 1, 1))
        self.assertEqual(ab['asr_text_equal'], {'true': 0, 'false': 0, 'unknown': 0})

    def test_latin_answers_count_rounds_including_failures_but_not_warmup(self):
        rows = [turn('latin'), turn('plain'), turn('warm'), turn('accent'), turn('missing')]
        rows[0]['terminal']['state']['text'] = '用 Google Drive 保存。'
        rows[2]['terminal']['state']['text'] = 'warmup Latin'
        rows[2]['warmup'] = True
        rows[3]['terminal']['state']['text'] = 'café'
        rows[3]['client_error'] = 'broken'
        del rows[4]['terminal']['state']['text']
        result = self.analyze(rows)
        self.assertIn('latin_answer_rounds', result['modes']['A'], 'Latin TTS limitation analysis is missing')
        self.assertEqual(result['modes']['A']['latin_answer_rounds'], 2)
        self.assertEqual(result['modes']['A']['answer_text_observed_n'], 3)
        self.assertEqual(result['latin_answer_rounds'], 2)
        self.assertIn('en_callable=None', result['notes']['tts_latin'])
        self.assertIn('no audio quality score', result['notes']['tts_latin'])

    def test_browser_actual_export_derives_render_device_and_underruns_separately(self):
        result = self.analyze([], browser_records=[browser_turn()])
        point = result['browser']['points'][0]
        self.assertIn('success', point, 'actual playback export schema is not adapted')
        self.assertTrue(point['success'])
        self.assertEqual(point['replay_end_to_first_pcm_ms'], 100)
        self.assertEqual(point['first_non_silent_render_ms'], 200)
        self.assertEqual(point['device_output_estimate_ms'], 210)
        self.assertIsNone(point['acoustic_first_sound_ms'])
        self.assertEqual((point['underrun_count'], point['underrun_duration_ms']), (2, 10))
        self.assertEqual(result['browser']['modes']['A']['first_non_silent_render_ms']['n'], 1)

    def test_browser_silence_no_api_or_cross_clock_preserves_null(self):
        row = browser_turn()
        row['evidence']['get_output_timestamp_supported'] = False
        row['evidence']['playback_events'] = [{'type': 'playback_progress'}]
        row['timestamps']['first_non_silent_render_perf_ms'] = None
        row['timestamps']['acoustic_first_sound_perf_ms'] = 1300  # no loopback capture exists
        point = self.analyze([], browser_records=[row])['browser']['points'][0]
        self.assertIn('replay_end_to_first_pcm_ms', point, 'browser clock analysis is missing')
        self.assertIsNone(point['first_non_silent_render_ms'])
        self.assertIsNone(point['device_output_estimate_ms'])
        self.assertIsNone(point['acoustic_first_sound_ms'])
        row = browser_turn()
        row['timestamps']['clock_domain'] = 'server_monotonic'
        point = self.analyze([], browser_records=[row])['browser']['points'][0]
        self.assertIsNone(point['replay_end_to_first_pcm_ms'])
        self.assertIsNone(point['first_non_silent_render_ms'])
        row = browser_turn()
        row['evidence']['clock_anchors'] = []
        self.assertIsNone(self.analyze([], browser_records=[row])['browser']['points'][0]['first_non_silent_render_ms'])

    def test_browser_early_error_and_length_never_enter_success_percentiles(self):
        rows = [browser_turn() for _ in range(4)]
        rows[1]['terminal']['events'][0]['sample_offset'] = 128
        rows[2]['client_error'] = 'failed'
        rows[3]['terminal']['finish_reason'] = 'length'
        result = self.analyze([], browser_records=rows)
        group = result['browser']['modes']['A']
        self.assertIn('counts', group, 'browser denominator accounting is missing')
        self.assertEqual(group['n'], 4)
        self.assertEqual(group['counts']['success'], 1)
        self.assertEqual(group['counts']['early'], 1)
        self.assertEqual(group['first_non_silent_render_ms']['n'], 1)

    def test_matplotlib_plot_uses_success_points_and_leaves_unmeasured_empty(self):
        path = HERE / 'plot.py'
        self.assertTrue(path.exists(), 'exp14 static plot has not been implemented')
        spec = importlib.util.spec_from_file_location('exp14_plot', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        summary = self.analyze([turn(), {**turn('early'), 'endpoint_early': True}])
        fig = module.build_figure(summary)
        self.addCleanup(lambda: module.plt.close(fig))
        scatter = fig.axes[0]
        self.assertEqual(sum(len(c.get_offsets()) for c in scatter.collections), 1)
        self.assertEqual([p.get_height() for p in fig.axes[1].patches], [1])
        self.assertEqual(len(fig.axes[2].collections), 0)
        empty = module.build_figure(self.analyze([]))
        self.addCleanup(lambda: module.plt.close(empty))
        self.assertEqual(len(empty.axes[0].collections), 0)
        self.assertEqual(len(empty.axes[1].patches), 0)
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'summary.json', Path(tmp) / 'figure.png'
            source.write_text(json.dumps(summary))
            proc = subprocess.run([sys.executable, '-B', str(path), '--summary', str(source),
                                   '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output.read_bytes().startswith(b'\x89PNG'))


if __name__ == '__main__':
    unittest.main()
