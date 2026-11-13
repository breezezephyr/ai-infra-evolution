"""Offline raw-wire fixtures and destructive evidence mutations; no server imports.

Fixtures model the native audit wire schema; they are not model-call evidence.
Run: python3 -B -m unittest discover -s phase5/exp27 -p test_analyze.py -v
"""
import copy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

D = Path(__file__).resolve().parent
USAGE = dict(prompt_tokens=7, completion_tokens=2, total_tokens=9)
HOOKS = ['AsyncLLMEngine.add_request', 'AsyncLLMEngine.abort', 'AsyncLLMEngine._abort',
         'RequestTracker.abort_request', 'RequestTracker.process_request_output',
         'LLMEngine.abort_request', 'LLMEngine.step', '_AsyncLLMEngine.step_async',
         'AsyncLLMEngine.engine_step']


def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sha(v):
    return hashlib.sha256(v if isinstance(v, bytes) else v.encode()).hexdigest()


def wire(v):
    return 'data: ' + json.dumps(v, ensure_ascii=False) + '\n\n'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(out):
    plan = load_module('exp27_fixture_plan', D / 'plan.py').make_plan()
    identity = dict(model_sha256='a' * 64, tokenizer_sha256='b' * 64, template_sha256='c' * 64)
    plan['identity'] = identity
    gateway, clients, backend, health = [], [], [], []
    tick = 0

    def native(event, **kw):
        nonlocal tick
        tick += 1
        return dict(schema='exp27.backend.v1', clock_domain='backend-3', pid=300,
                    backend_monotonic_ns=tick, event=event, **kw)

    backend.append(native('hooks_installed', installed=True, vllm_version='0.8.5', hooks=HOOKS))
    previous_cold = None
    for n, c in enumerate(plan['cases']):
        name, rid = c['case_id'], c['request_id']
        terminal = c['allowed_terminals'][0]
        count = c['expected_attempts']
        if name.startswith('burst-'):
            count = int(int(name[-1]) < 2)
            terminal = 'completed' if count else 'admission_rejected'
        cache = c.get('expected_cache', 'bypass' if c['route'] == 'direct' else 'miss')
        if count == 0 and cache != 'hit':
            cache = 'not_checked'
        policy = 'rule-v2' if name in ('policy-change', 'tenant-change') else 'rule-v1'
        native_body = {**copy.deepcopy(c['body']), 'model': 'exp27-qwen3-0.6b', 'stream_options': {'include_usage': True}, 'chat_template_kwargs': {'enable_thinking': False}}
        prompt_hash = sha(canonical([1, 2, 3, 4, 5, 6, 7]))
        key = sha(canonical({'tenant': c['tenant'], 'body': native_body, 'prompt_ids_sha256': prompt_hash, 'policy': policy, 'identity': identity}))
        start = n * 10000
        r = dict(case_id=name, request_id=rid, generation_id='g0', mode='gpu',
                 idempotency_key=c['idempotency_key'], input_body=copy.deepcopy(c['body']),
                 input_sha256=sha(canonical(c['body'])), prompt_ids_sha256=prompt_hash, tenant_id=None if name == 'reject-auth' else c['tenant'],
                 route=c['route'], stratum=c['stratum'], cache=cache, cache_key=key,
                 cache_origin=None, policy=policy, identity=identity, prompt_tokens=None if name in ('reject-auth', 'reject-tools', 'drain-new-entry') else 7,
                 admission_wait_ns=0, ingress_ns=start, started_ns=start, ended_ns=start + 999,
                 clock_domain='gateway-1', attempts=[], events=[], settlements=[],
                 terminal=terminal, sent_content='', committed=False)

        def event(kind, **kw):
            r['events'].append(dict(event=kind, ns=start + len(r['events']) + 1, **kw))

        packets = []
        for i in range(count):
            aid = rid + '/a' + str(i + 1)
            retry = count == 2 and i == 0
            text = '' if retry or terminal in ('client_disconnected', 'drain_timeout') else ('LAB_BLOCK' if terminal == 'review_rejected' else c['expected_text'])
            finish = 'length' if name == 'truncated' else 'stop'
            if name == 'truncated':
                text = '1,'
            outcome = 'first_content_timeout' if retry else terminal
            usage = None if retry else copy.deepcopy(USAGE)
            raw = wire({'choices': [{'delta': {'content': text}, 'finish_reason': None}]}) if text else ''
            # A cancelled HTTP consumer can leave a naturally completed engine.
            if not retry:
                raw += wire({'choices': [{'delta': {}, 'finish_reason': finish}]}) + wire({'choices': [], 'usage': usage}) + 'data: [DONE]\n\n'
            body = {**copy.deepcopy(c['body']), 'model': 'exp27-qwen3-0.6b', 'stream_options': {'include_usage': True},
                    'chat_template_kwargs': {'enable_thinking': False}}
            a = dict(request_id=rid, attempt_id=aid, mode='gpu', injected_fault=(c['faults'] + [None, None])[i],
                     started_ns=start + i * 500, ended_ns=start + (i + 1) * 500, worker_joined=True, outcome=outcome,
                     generated_content='' if terminal == 'review_rejected' else text, raw_sse=raw, finish=finish if not retry else None,
                     usage=usage, usage_source='native_stream_usage' if usage else 'unknown',
                     http_status=200, backend_body=body, backend_body_sha256=sha(canonical(body)))
            r['attempts'].append(a)
            event('attempt_started', attempt_id=aid)
            if text and terminal != 'review_rejected':
                event('generated', attempt_id=aid, text=text)
            if text and terminal in ('completed', 'backend_error'):
                event('content_send_started', attempt_id=aid)
                event('content_sent', attempt_id=aid, text=text)
                packets.append(dict(type='content', id=rid, generation_id='g0', attempt_id=aid, content=text))
                r['sent_content'] += text
            event('worker_exited', attempt_id=aid)
            event('attempt_joined', attempt_id=aid)
            r['settlements'].append(dict(attempt_id=aid, usage=usage, source=a['usage_source']))
            if retry:
                event('retry_allowed', from_attempt=aid)
            hid, eid = 'h-' + aid, 'e-' + aid
            common = dict(request_id=rid, attempt_id=aid, http_id=hid)
            backend.append(native('http_started', **common))
            backend.append(native('engine_request', engine_request_id=eid, **common))
            if retry:
                backend.append(native('abort_called', engine_request_id=eid, hook='AsyncLLMEngine.abort', **common))
                backend.append(native('abort_returned', engine_request_id=eid, hook='AsyncLLMEngine.abort', error=None, **common))
            else:
                backend.append(native('engine_finished', engine_request_id=eid, finished=True, **common))
            backend.append(native('state_after', snapshot_complete=True, queues=[], cached=[],
                                  tracker=dict(active_stream=False, new_pending=False, abort_pending=False),
                                  scheduler_unfinished=False, engine_pending_or_unfinished=False,
                                  pending_or_unfinished=False, error=None, **common))
            backend.append(native('http_request_chunk',body_b64=base64.b64encode(canonical(body)).decode(),more_body=False,**common))
            backend.append(native('http_response_chunk',body_b64=base64.b64encode(raw.encode()).decode(),more_body=False,stage='before_send',**common))
            backend.append(native('http_finished', component='backend-http', body=canonical(body).decode(),
                                  request_sha256=sha(canonical(body)), sse=raw, response_sha256=sha(raw),
                                  status=200, started_ns=0, ended_ns=tick,
                                  engine_request_ids=[eid], **common))
        if cache == 'hit':
            origin = previous_cold
            r['cache_origin'] = dict(request_id=origin['request_id'], attempt_id=origin['attempts'][-1]['attempt_id'],
                                     usage=copy.deepcopy(USAGE), content_sha256=sha(origin['sent_content']), key=key)
            r['sent_content'] = origin['sent_content']
            packets = [dict(type='content', id=rid, generation_id='g0', attempt_id=None, content=r['sent_content'])]
            event('content_send_started', attempt_id=None)
            event('content_sent', attempt_id=None, text=r['sent_content'])
        if c['stratum'] == 'cache-cold':
            previous_cold = r
        if terminal in ('client_disconnected', 'drain_timeout'):
            event('stop_requested', reason=terminal)
        event('request_finished', terminal=terminal)
        r['committed'] = bool(r['sent_content'])
        r['sent_sha256'] = sha(r['sent_content'])
        closed = terminal == 'client_disconnected'
        if not closed:
            packets.append(dict(type='terminal', id=rid, generation_id='g0', terminal=terminal,
                                attempt_ids=[a['attempt_id'] for a in r['attempts']], settlements=copy.deepcopy(r['settlements']),
                                finish=('stop' if cache == 'hit' else r['attempts'][-1]['finish']) if terminal == 'completed' else None,
                                cache=cache, cache_origin=copy.deepcopy(r['cache_origin'])))
        raw = ''.join(wire(p) for p in packets) + ('' if closed else 'data: [DONE]\n\n')
        clients.append(dict(case_id=name, request_id=rid, status=200, raw=raw,
                            started_ns=start, first_content_ns=start + 100 if r['sent_content'] else None,
                            ended_ns=start + 900, clock_domain='client-2', closed_intentionally=closed))
        gateway.append(r)
        health.append(dict(case_ids=[name], state={'active': 0, 'workers': 0, 'reserved': 0}, ns=start + 1000))
    (out / 'code').mkdir()
    for name in ('plan.py', 'gateway.py', 'lifecycle.py', 'run.py', 'serve_gateway.py', 'analyze.py', 'backend_audit.py'):
        (out / 'code' / name).write_text('# frozen fixture ' + name)
        plan['source_sha256'][name] = sha((out / 'code' / name).read_bytes())
    write(out, 'plan.json', plan)
    freeze = dict(plan_sha256=sha((out / 'plan.json').read_bytes()), source_sha256=plan['source_sha256'], identity=identity)
    write(out, 'freeze.json', freeze)
    write(out, 'gateway-startup.json', {**freeze, 'pid': 100, 'port': 8127, 'clock_domain': 'gateway-1'})
    write(out,'backend-startup.json',{'pid':300,'clock_domain':'supervisor-4','started_ns':0,'source_sha256':plan['source_sha256'],'command':['vllm','serve','/opt/models/Qwen3-0.6B','--served-model-name','exp27-qwen3-0.6b','--port','8027','--disable-frontend-multiprocessing','--middleware','backend_audit.AuditMiddleware']})
    for name, rows in (('gateway.jsonl', gateway), ('clients.json', clients), ('backend.jsonl', backend), ('health.json', health)):
        write(out, name, rows)
    write(out, 'resources.json', dict(clock_domain='supervisor-4', intervals=[
        dict(component='backend', pid=300, started_ns=0, ready_ns=100, stop_requested_ns=800, exited_ns=1000, returncode=0),
        dict(component='gateway', pid=100, started_ns=200, ready_ns=300, stop_requested_ns=900, exited_ns=950, returncode=0)],
        cpu={'backend': dict(user_seconds=0.2, system_seconds=0.1), 'gateway': dict(user_seconds=0.1, system_seconds=0.1)}))
    write(out, 'model-identity.json', dict(files={'model.safetensors': 'a' * 64, 'tokenizer.json': 'b' * 64, 'config.json': 'd' * 64, 'tokenizer_config.json': 'e' * 64}, template_sha256='c' * 64))
    write(out, 'cleanup.json', dict(all_reaped=True, ports={'8027': False, '8127': False}, owned_pids=[100, 300], model_files_unchanged={k: True for k in ['model.safetensors', 'tokenizer.json', 'config.json', 'tokenizer_config.json']}))


def read(out, name):
    raw = (out / name).read_text()
    return [json.loads(x) for x in raw.splitlines()] if name.endswith('.jsonl') else json.loads(raw)


def write(out, name, value):
    (out / name).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in value) if name.endswith('.jsonl') else json.dumps(value, ensure_ascii=False))


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((D / 'analyze.py').exists(), 'independent exp27 analyzer has not been implemented')
        self.module = load_module('exp27_independent_auditor', D / 'analyze.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        fixture(self.out)

    def reject(self, code=None):
        result = self.module.analyze(self.out)
        self.assertFalse(result['accepted'])
        self.assertIsNone(result['metrics'])
        if code:
            self.assertIn(code, [e['code'] for e in result['errors']], result['errors'])
        return result

    def test_full_wire_42_requests_cache_not_charged_and_unknown_quality(self):
        r = self.module.analyze(self.out)
        self.assertTrue(r['accepted'], r['errors'])
        self.assertEqual((r['planned'], r['eligible']), (42, 37))
        self.assertEqual(r['metrics']['gpu']['attempts'], 29)
        self.assertEqual(r['metrics']['gpu']['known_total_tokens'], 252)
        self.assertEqual(r['metrics']['gpu']['unknown_usage_attempts'], 1)
        self.assertEqual(r['metrics']['resource']['process_union_ns'], 1000)
        self.assertEqual(r['metrics']['resource']['ready_union_ns'], 800)
        cancelled = next(x for x in r['requests'] if x['case_id'] == 'client-cancel')
        self.assertIsNone(cancelled['quality'])
        self.assertFalse(cancelled['joint'])
        self.assertEqual(r['metrics']['joint']['denominator'], 42)
        self.assertEqual(r['metrics']['joint_eligible']['denominator'], 37)

    def test_mutated_sse_fields_finish_settlement_and_duplicate_usage_reject(self):
        original = read(self.out, 'clients.json')
        for field, value in [('id', 'other'), ('generation_id', 'g9'), ('attempt_id', None), ('content', '8')]:
            with self.subTest(field=field):
                rows = copy.deepcopy(original)
                packet, tail = rows[0]['raw'].split('\n\n', 1)
                obj = json.loads(packet[6:]); obj[field] = value
                rows[0]['raw'] = wire(obj) + tail
                write(self.out, 'clients.json', rows)
                self.reject('client_content_packets')
        write(self.out, 'clients.json', original)
        g = read(self.out, 'gateway.jsonl')
        g[0]['attempts'][0]['raw_sse'] = g[0]['attempts'][0]['raw_sse'].replace('data: [DONE]', wire({'choices': [], 'usage': USAGE}) + 'data: [DONE]')
        write(self.out, 'gateway.jsonl', g)
        self.reject('native_sse')

    def test_backend_only_usage_retained_but_refuses_formal_metrics(self):
        g = read(self.out, 'gateway.jsonl')
        g[0]['attempts'][0].update(usage=None, usage_source='unknown', raw_sse='')
        g[0]['settlements'][0].update(usage=None, source='unknown')
        write(self.out, 'gateway.jsonl', g)
        r = self.reject('usage_reconciliation')
        self.assertEqual(r['attempt_ledger'][0]['resource_usage'], USAGE)
        self.assertEqual(r['attempt_ledger'][0]['resource_usage_source'], 'backend_http')

    def test_cross_tenant_origin_and_forged_input_are_rejected(self):
        g = read(self.out, 'gateway.jsonl')
        g[2]['cache_origin']['request_id'] = 'exp27-tenant-b-repeat0-cold'
        g[0]['input_body']['messages'][0]['content'] = 'forged'
        write(self.out, 'gateway.jsonl', g)
        self.reject('cache_origin')

    def test_cancelled_engine_must_clear_even_after_natural_finish(self):
        b = read(self.out, 'backend.jsonl')
        b = [x for x in b if not (x.get('request_id') == 'exp27-client-cancel' and x.get('event') == 'state_after')]
        write(self.out, 'backend.jsonl', b)
        self.reject('native_not_quiescent')

    def test_same_client_clock_slo_is_request_intersection_not_audit_failure(self):
        c = read(self.out, 'clients.json')
        c[0].update(first_content_ns=c[0]['started_ns'] + 1000000001, ended_ns=c[0]['started_ns'] + 2000000000)
        write(self.out, 'clients.json', c)
        r = self.module.analyze(self.out)
        self.assertTrue(r['accepted'], r['errors'])
        self.assertFalse(r['requests'][0]['slo'])
        self.assertFalse(r['requests'][0]['joint'])

    def test_source_mutation_and_cli_failure_null_metrics(self):
        (self.out / 'code' / 'gateway.py').write_text('# tampered')
        self.reject('source_hash')
        path = self.out / 'revision' / 'summary.json'
        proc = subprocess.run([sys.executable, '-B', str(D / 'analyze.py'), '--out', str(self.out), '--summary', str(path)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIsNone(json.loads(path.read_text())['metrics'])


if __name__ == '__main__':
    unittest.main()

class ReviewRegressions(unittest.TestCase):
    setUp=AnalyzerTests.setUp
    reject=AnalyzerTests.reject

    def test_original_chunk_usage_cannot_be_erased_by_aggregated_rows(self):
        g=read(self.out,'gateway.jsonl');a=g[0]['attempts'][0];aid=a['attempt_id']
        def strip_usage(raw):
            return ''.join(f+'\n\n' for f in raw.split('\n\n') if f and '"usage"' not in f)
        a.update(raw_sse=strip_usage(a['raw_sse']),usage=None,usage_source='unknown',usage_frames=[])
        g[0]['settlements'][0].update(usage=None,source='unknown');write(self.out,'gateway.jsonl',g)
        c=read(self.out,'clients.json');frames=c[0]['raw'].split('\n\n');changed=[]
        for f in frames:
            if f.startswith('data: {'):
                obj=json.loads(f[6:])
                if obj.get('type')=='terminal':obj['settlements']=g[0]['settlements']
                changed.append(wire(obj))
            elif f:changed.append(f+'\n\n')
        c[0]['raw']=''.join(changed);write(self.out,'clients.json',c)
        b=read(self.out,'backend.jsonl');h=next(x for x in b if x.get('event')=='http_finished' and x['attempt_id']==aid)
        h['sse']=strip_usage(h['sse']);h['response_sha256']=sha(h['sse'])
        import base64
        h['response_b64']=base64.b64encode(h['sse'].encode()).decode();h['send_returned_b64']=h['response_b64'];write(self.out,'backend.jsonl',b)
        r=self.reject();entry=next(x for x in r['attempt_ledger'] if x['attempt_id']==aid)
        self.assertEqual(entry['backend_chunk_usage'],USAGE);self.assertEqual(entry['resource_usage'],USAGE)

    def test_invalid_request_or_response_chunk_base64_is_rejected(self):
        original=read(self.out,'backend.jsonl')
        for kind in ['http_request_chunk','http_response_chunk']:
            b=copy.deepcopy(original);x=next(x for x in b if x['event']==kind);x['body_b64']='NOT BASE64'
            write(self.out,'backend.jsonl',b);self.reject()

    def test_wrong_resource_pid_cannot_bind_to_cleanup_only(self):
        r=read(self.out,'resources.json');c=read(self.out,'cleanup.json')
        for i,x in enumerate(r['intervals']):x.update(pid=900000+i,started_ns=0,ready_ns=0,stop_requested_ns=1,exited_ns=1)
        c['owned_pids']=[900000,900001];write(self.out,'resources.json',r);write(self.out,'cleanup.json',c);self.reject()

    def test_backend_startup_is_required(self):
        p=self.out/'backend-startup.json'
        if p.exists():p.unlink()
        self.reject()

    def test_backend_start_time_matches_resource_interval(self):
        r=read(self.out,'resources.json');r['intervals'][0]['started_ns']=1
        write(self.out,'resources.json',r);self.reject()
