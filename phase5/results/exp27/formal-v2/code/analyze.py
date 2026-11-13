"""Independent, stdlib-only exp27 evidence auditor. Never imports server code.

API analyze(out, summary_path=None); CLI --out DIR [--summary FILE].
Required files: plan.json, freeze.json, gateway-startup.json, code/*,
gateway.jsonl, clients.json, backend.jsonl, health.json, resources.json, cleanup.json.
Plan/source hashes use file bytes; input/cache/body hashes use canonical JSON.
The ex-ante contract is pinned below, independently of runtime plan.py imports.
Plan/startup identity is checked against model-identity.json files/template hashes.
health has one row per step with case_ids. resources.json uses intervals and
cpu wait4 values from one supervisor clock. Ready ends at stop_requested_ns.
CPU rusage is process-reap scope, never per-request GPU.
Any invalid evidence => metrics=null; diagnostic ledgers remain available.
A valid audit need not mean all requests met quality/SLO. Null means unknown.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

CONTRACT_SHA256 = "26b3986a7d3f57a6193ee3ed07fed3f9018a74a553122ba3f4fe1172f026ca7b"
CONTRACT_FIELDS = ("experiment", "schema", "seed", "backend_port", "gateway_port",
                   "active_limit", "waiting_limit", "prompt_limit", "slo", "cases",
                   "steps", "scope", "quality")

TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key: " + key)
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON: " + value)))


def _sse(raw):
    """Frame actual SSE boundaries; do not salvage an unfinished JSON packet."""
    errors, objects, order = [], [], []
    if not isinstance(raw, str):
        return dict(objects=[], order=[], done_count=0, tail="", errors=["SSE must be text"])
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    frames = raw.split("\n\n")
    tail = frames.pop()
    done = 0
    for frame in frames:
        data = []
        for line in frame.split("\n"):
            if line.startswith("data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(" ") else value)
        if not data:
            continue
        value = "\n".join(data)
        if done:
            errors.append("event after DONE")
        if value == "[DONE]":
            done += 1
            order.append("done")
            continue
        try:
            obj = _json(value)
            if not isinstance(obj, dict):
                raise ValueError("SSE data must be an object")
            objects.append(obj)
            order.append(obj)
        except (ValueError, TypeError) as exc:
            errors.append("malformed SSE: " + str(exc))
    return dict(objects=objects, order=order, done_count=done, tail=tail, errors=errors)


def _valid_usage(usage):
    return (isinstance(usage, dict)
            and all(type(usage.get(k)) is int and usage[k] >= 0 for k in TOKEN_FIELDS)
            and usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"])


def parse_native_sse(raw):
    """Parse full/partial OpenAI native SSE independently, preserving partial usage.

    Complete, delimited usage frames count even if the stream has no DONE.
    Incomplete tails never supply usage. Invalid complete packets remain errors.
    """
    parsed = _sse(raw)
    errors = list(parsed["errors"])
    usage, finish, content = None, None, ""
    for obj in parsed["objects"]:
        if obj.get("usage") is not None:
            if usage is not None:
                errors.append("duplicate usage frame")
            usage = obj["usage"]
            if not _valid_usage(usage):
                errors.append("invalid native token usage")
        choices = obj.get("choices", [])
        if not isinstance(choices, list):
            errors.append("native choices must be a list")
            continue
        if len(choices) > 1:
            errors.append("multiple native choices outside text-only contract")
        for choice in choices:
            if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                errors.append("invalid native choice/delta")
                continue
            text = choice.get("delta", {}).get("content")
            if text is not None and not isinstance(text, str):
                errors.append("native content must be text")
            elif text:
                if finish is not None:
                    errors.append("native content after finish")
                content += text
            if choice.get("finish_reason") is not None:
                if finish is not None:
                    errors.append("duplicate native finish")
                finish = choice["finish_reason"]
    complete = (parsed["done_count"] == 1 and not parsed["tail"].strip()
                and finish in ("stop", "length") and not errors)
    return dict(usage=usage, content=content, finish=finish, done_count=parsed["done_count"],
                complete=complete, partial=not complete, tail=parsed["tail"], errors=errors)


class _Audit:
    def __init__(self, out, summary_path=None):
        self.out = Path(out)
        self.summary_path = Path(summary_path) if summary_path is not None else self.out / "summary.json"
        self.errors, self.ledger, self.requests = [], [], []
        self.attempt_ids = set()
        self.request_errors = {}
        self.identity = None

    def check(self, condition, code, context, detail=""):
        if not condition:
            self.errors.append(dict(code=code, context=context, detail=str(detail)))
        return bool(condition)

    def load(self, name, rows=False):
        try:
            raw = (self.out / name).read_text(encoding="utf-8")
            value = [_json(line) for line in raw.splitlines() if line.strip()] if name.endswith("jsonl") else _json(raw)
            if rows and (not isinstance(value, list) or any(not isinstance(v, dict) for v in value)):
                raise ValueError("expected list of object rows")
            if not rows and not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except (OSError, ValueError, TypeError) as exc:
            self.check(False, "input", name, exc)
            return [] if rows else {}

    def unique(self, rows, key, context):
        result = {}
        for row in rows:
            value = row.get(key)
            if self.check(isinstance(value, str) and bool(value), "missing_id", context, key):
                self.check(value not in result, "duplicate_" + key, context, value)
                if value not in result:
                    result[value] = row
        return result

    def provenance(self, plan, gateway):
        freeze, startup = self.load('freeze.json'), self.load('gateway-startup.json')
        try:
            plan_hash = _sha((self.out / 'plan.json').read_bytes())
        except OSError:
            plan_hash = None
        sources = plan.get('source_sha256', {})
        required = {'plan.py', 'gateway.py', 'lifecycle.py', 'serve_gateway.py', 'run.py', 'analyze.py', 'backend_audit.py'}
        if not self.check(isinstance(sources, dict) and required <= set(sources), 'source_manifest', 'plan'):
            sources = sources if isinstance(sources, dict) else {}
        for obj, label in ((freeze, 'freeze'), (startup, 'gateway-startup')):
            self.check(obj.get('plan_sha256') == plan_hash and plan_hash is not None, 'plan_hash', label)
            self.check(obj.get('source_sha256') == sources, 'source_manifest', label)
        for name, digest in sources.items():
            if not self.check(isinstance(name, str) and Path(name).name == name and name.endswith('.py'), 'source_path', str(name)):
                continue
            try:
                self.check(_sha((self.out / 'code' / name).read_bytes()) == digest, 'source_hash', name)
            except OSError as exc:
                self.check(False, 'source_hash', name, exc)
        self.identity = plan.get('identity')
        identity = self.load('model-identity.json')
        files = identity.get('files', {})
        expected = dict(model_sha256=files.get('model.safetensors'), tokenizer_sha256=files.get('tokenizer.json'), template_sha256=identity.get('template_sha256'))
        self.check(isinstance(self.identity, dict) and self.identity == expected and all(isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v) for v in expected.values()), 'model_identity', 'plan')
        self.check(startup.get('identity') == self.identity, 'model_identity', 'startup')
        self.check(type(startup.get('pid')) is int and startup['pid'] > 0, 'startup_pid', 'gateway-startup')
        self.check(startup.get('port', plan.get('gateway_port')) == plan.get('gateway_port') == 8127, 'startup_port', 'gateway-startup')
        domain = startup.get('clock_domain')
        self.check(isinstance(domain, str) and bool(domain), 'clock_domain', 'gateway-startup')
        for row in gateway:
            self.check(row.get('clock_domain') == domain, 'clock_domain', str(row.get('case_id')))

    def audit_plan(self, plan):
        # Pin all ex-ante inputs/steps/quality, without executing a runtime builder.
        self.check(_sha(_canonical({k: plan.get(k) for k in CONTRACT_FIELDS})) == CONTRACT_SHA256,
                   'plan_contract', 'plan', '42 requests, 37 eligible; frozen before observation')
        cases = plan.get('cases', [])
        if not self.check(isinstance(cases, list) and all(isinstance(c, dict) for c in cases), 'plan_cases', 'plan'):
            return {}
        indexed = self.unique(cases, 'case_id', 'plan')
        self.unique(cases, 'request_id', 'plan')
        self.check(len(cases) == len(indexed) == 42 and sum(c.get('eligible') is True for c in cases) == 37,
                   'plan_denominator', 'plan')
        return indexed

    def time_bounds(self, row, context):
        start, end = row.get('started_ns'), row.get('ended_ns')
        return self.check(type(start) is int and type(end) is int and 0 <= start <= end, 'time_bounds', context)

    def request(self, case, row, client, policy):
        name, rid = case['case_id'], case['request_id']
        initial = len(self.errors)
        for field in ('case_id', 'request_id', 'generation_id', 'mode', 'idempotency_key', 'route', 'stratum'):
            self.check(row.get(field) == case.get(field), 'gateway_' + field, name)
        self.check(row.get('terminal') in case['allowed_terminals'], 'gateway_terminal', name)
        self.check(client.get('case_id') == name and client.get('request_id') == rid, 'client_identity', name)
        self.check(row.get('tenant_id') == (None if name == 'reject-auth' else case['tenant']), 'tenant', name)
        self.check(row.get('input_body') == case['body'] and row.get('input_sha256') == _sha(_canonical(case['body'])), 'input_hash', name)
        self.check(row.get('identity') == self.identity, 'model_identity', name)
        self.check(row.get('policy') == policy, 'policy', name)
        for field in ('admission_wait_ns', 'ingress_ns'):
            self.check(type(row.get(field)) is int and row[field] >= 0, 'gateway_' + field, name)
        unencoded = row.get('terminal') in ('authentication_rejected', 'capability_rejected', 'draining')
        self.check(row.get('prompt_tokens') is None if unencoded else type(row.get('prompt_tokens')) is int and row['prompt_tokens'] >= 0, 'gateway_prompt_tokens', name)
        self.time_bounds(row, name)
        self.time_bounds(client, name + ':client')
        self.check(isinstance(client.get('clock_domain'), str) and bool(client['clock_domain']), 'client_clock', name)
        self.check(not client.get('error') and not client.get('error_type'), 'client_error', name)
        attempts, events, settlements = row.get('attempts'), row.get('events'), row.get('settlements')
        for value, label in ((attempts, 'attempts'), (events, 'events'), (settlements, 'settlements')):
            if not self.check(isinstance(value, list) and all(isinstance(v, dict) for v in value), 'row_schema', name, label):
                return
        cache, terminal = row.get('cache'), row.get('terminal')
        self.check(cache in ('miss', 'hit', 'bypass', 'not_checked'), 'cache_state', name)
        if 'expected_cache' in case:
            self.check(cache == case['expected_cache'], 'cache_expected', name)
        if case['route'] == 'direct':
            self.check(cache == 'bypass', 'cache_direct', name)
        native_body = {**case['body'], 'model': 'exp27-qwen3-0.6b',
                       'stream_options': {'include_usage': True}, 'chat_template_kwargs': {'enable_thinking': False}}
        if cache in ('hit', 'miss', 'bypass'):
            prompt_hash = row.get('prompt_ids_sha256')
            self.check(isinstance(prompt_hash, str) and len(prompt_hash) == 64 and all(c in '0123456789abcdef' for c in prompt_hash), 'prompt_hash', name)
            self.check(row.get('cache_key') == _sha(_canonical(dict(tenant=row.get('tenant_id'), body=native_body,
                       prompt_ids_sha256=prompt_hash, identity=self.identity, policy=policy))), 'cache_key', name)
        if case['expected_attempts'] is not None:
            count = case['expected_attempts']
        else:
            count = 1 if terminal == 'completed' else 0
        self.check(len(attempts) == count and len(attempts) <= 2, 'attempt_count', name)
        self.check((cache == 'hit') == (case.get('expected_cache') == 'hit'), 'cache_hit_plan', name)
        self.check(cache != 'hit' or not attempts and not settlements, 'cache_generation_zero', name)
        if cache != 'hit':
            self.check(row.get('cache_origin') is None, 'cache_origin', name)
        indexed = self.unique(attempts, 'attempt_id', name)
        s_indexed = self.unique(settlements, 'attempt_id', name + ':settlements')
        self.check(len(settlements) == len(attempts) and set(indexed) == set(s_indexed), 'settlement_coverage', name)
        previous_ns = row.get('started_ns', 0)
        pending, sent_events, stops = False, [], []
        for pos, e in enumerate(events):
            ns, kind, aid = e.get('ns'), e.get('event'), e.get('attempt_id')
            self.check(type(ns) is int and type(previous_ns) is int and previous_ns <= ns <= row['ended_ns'], 'event_order', name)
            if type(ns) is int:
                previous_ns = ns
            if 'attempt_id' in e:
                self.check(aid in indexed or aid is None and cache == 'hit', 'event_attempt', name)
            if kind == 'stop_requested':
                stops.append(pos)
                self.check(e.get('reason') == terminal, 'stop_reason', name)
            if kind == 'content_send_started':
                self.check(not pending and not stops, 'send_started_after_stop', name)
                pending = (aid, pos)
            elif kind == 'content_sent':
                self.check(bool(pending) and pending[0] == aid, 'send_commit_without_start', name)
                pending = False
                self.check(isinstance(e.get('text'), str) and bool(e['text']), 'sent_text', name)
                sent_events.append((pos, e))
        self.check(not pending, 'uncommitted_send', name)
        self.check(len(stops) == (1 if terminal in ('client_disconnected', 'drain_timeout') else 0), 'stop_count', name)
        sent = ''.join(e.get('text', '') for _, e in sent_events)
        self.check(sent == row.get('sent_content') and row.get('sent_sha256') == _sha(sent), 'sent_content', name)
        self.check(row.get('committed') is bool(sent_events), 'commit_flag', name)
        finished = [e for e in events if e.get('event') == 'request_finished']
        # Entry rejects can be recorded by the wrapper without a lifecycle run.
        self.check((not attempts and not finished) or
                   len(finished) == 1 and finished[0].get('terminal') == terminal, 'request_finished', name)
        for i, a in enumerate(attempts):
            aid = a.get('attempt_id')
            self.check(aid not in self.attempt_ids and aid == rid + '/a' + str(i + 1), 'attempt_identity', name)
            self.attempt_ids.add(aid)
            self.check(a.get('request_id') == rid and a.get('mode') == 'gpu', 'attempt_owner', str(aid))
            self.check(a.get('worker_joined') is True, 'worker_not_joined', str(aid))
            self.time_bounds(a, str(aid))
            self.check(a.get('injected_fault') == (case['faults'] + [None, None])[i], 'attempt_fault', str(aid))
            positions = {}
            for kind in ('attempt_started', 'worker_exited', 'attempt_joined'):
                found = [j for j, e in enumerate(events) if e.get('event') == kind and e.get('attempt_id') == aid]
                self.check(len(found) == 1, 'attempt_lifecycle', str(aid), kind)
                positions[kind] = found[0] if found else -1
            self.check(positions['attempt_started'] < positions['worker_exited'] < positions['attempt_joined'], 'join_order', str(aid))
            generated = ''.join(e.get('text', '') for e in events if e.get('event') == 'generated' and e.get('attempt_id') == aid)
            delivered = ''.join(e['text'] for _, e in sent_events if e.get('attempt_id') == aid)
            self.check(generated == a.get('generated_content') and generated.startswith(delivered), 'generated_content', str(aid))
            for pos, e in sent_events:
                if e.get('attempt_id') == aid:
                    self.check(positions['attempt_started'] < pos < positions['attempt_joined'], 'send_lifecycle', str(aid))
            if i:
                prior = attempts[i - 1]
                joins = [j for j, e in enumerate(events) if e.get('event') == 'attempt_joined' and e.get('attempt_id') == prior['attempt_id']]
                retries = [j for j, e in enumerate(events) if e.get('event') == 'retry_allowed' and e.get('from_attempt') == prior['attempt_id']]
                self.check(bool(joins) and len(retries) == 1 and joins[0] < retries[0] < positions['attempt_started'], 'retry_order', name)
                self.check(not any(j < positions['attempt_started'] for j, _ in sent_events) and bool(row.get('idempotency_key')), 'retry_after_commit', name)
                self.check(prior.get('outcome') in ('connect_refused', 'first_content_timeout', 'backend_http_error', 'incomplete_stream'), 'retry_outcome', name)
                self.check(prior.get('ended_ns', -1) <= a.get('started_ns', -1), 'retry_overlap', name)
            usage, source = a.get('usage'), a.get('usage_source')
            valid_usage = usage is None or _valid_usage(usage)
            self.check(valid_usage, 'invalid_usage', str(aid))
            self.check(source == ('unknown' if usage is None else 'native_stream_usage'), 'usage_source', str(aid))
            self.check(s_indexed.get(aid) == dict(attempt_id=aid, usage=usage, source=source), 'settlement_value', str(aid))
            native = parse_native_sse(a.get('raw_sse'))
            self.check(not native['errors'], 'native_sse', str(aid), native['errors'])
            self.check(native['usage'] == usage, 'native_usage', str(aid))
            self.check(native['content'].startswith(a.get('generated_content', '')), 'native_generated_prefix', str(aid))
            if 'backend_generated_content' in a:
                self.check(a.get('backend_generated_content') == native['content'], 'backend_generated_content', str(aid))
            if terminal == 'review_rejected':
                self.check(native['complete'] and 'LAB_BLOCK' in native['content'] and generated == '', 'review_native', str(aid))
            if a.get('outcome') == 'completed':
                self.check(native['complete'] and native['finish'] == a.get('finish') and native['content'] == generated, 'native_complete', str(aid))
            if i == len(attempts) - 1 and terminal == 'completed':
                self.check(a.get('outcome') == 'completed' and a.get('finish') in ('stop', 'length'), 'completed_attempt', str(aid))
            body = a.get('backend_body')
            self.check(body == native_body, 'backend_input', str(aid))
            self.ledger.append(dict(case_id=name, request_id=rid, attempt_id=aid, mode='gpu', tenant_id=case['tenant'],
                                    route=case['route'], stratum=case['stratum'], outcome=a.get('outcome'),
                                    retry=i > 0, usage=usage, usage_source=source, usage_known=usage is not None,
                                    native_usage=native['usage'], settlement=s_indexed.get(aid),
                                    resource_usage=usage if valid_usage else None,
                                    resource_usage_source=source if valid_usage else 'invalid'))
        self.check(sum(e.get('event') == 'retry_allowed' for e in events) == max(len(attempts) - 1, 0), 'retry_count', name)
        if terminal in ('review_rejected', 'authentication_rejected', 'capability_rejected', 'budget_rejected', 'admission_rejected', 'draining'):
            self.check(not sent_events, 'rejection_content', name)
        result = self.client(case, row, client, sent_events)
        self.request_errors[name] = len(self.errors) > initial
        self.requests.append(result)

    def client(self, case, row, client, sent_events):
        name, terminal = case['case_id'], row['terminal']
        parsed = _sse(client.get('raw'))
        self.check(not parsed['errors'], 'client_sse', name, parsed['errors'])
        expected = [dict(type='content', id=case['request_id'], generation_id='g0', attempt_id=e.get('attempt_id'), content=e['text']) for _, e in sent_events]
        observed = [p for p in parsed['objects'] if p.get('type') == 'content']
        closed = terminal == 'client_disconnected'
        self.check(client.get('closed_intentionally') is closed, 'intentional_disconnect', name)
        self.check(observed == (expected[:len(observed)] if closed else expected), 'client_content_packets', name)
        finish = (row['attempts'][-1].get('finish') if row['attempts'] else 'stop') if terminal == 'completed' else None
        packet = dict(type='terminal', id=case['request_id'], generation_id='g0', terminal=terminal,
                      attempt_ids=[a['attempt_id'] for a in row['attempts']], settlements=row['settlements'],
                      finish=finish, cache=row.get('cache'), cache_origin=row.get('cache_origin'))
        protocol = False
        if closed:
            self.check(not any(p.get('type') == 'terminal' for p in parsed['objects']) and parsed['done_count'] == 0, 'disconnect_terminal', name)
        elif client.get('status') == 200:
            protocol = parsed['order'] == expected + [packet, 'done'] and parsed['done_count'] == 1 and not parsed['tail'].strip()
            self.check(protocol, 'client_terminal', name)
        else:
            statuses = {'authentication_rejected': 401, 'capability_rejected': 400, 'budget_rejected': 400, 'admission_rejected': 429, 'draining': 503}
            try:
                self.check(client.get('status') == statuses.get(terminal) and _json(client['raw']) == {'request_id': case['request_id'], 'error': terminal}, 'client_rejection', name)
            except (ValueError, TypeError):
                self.check(False, 'client_rejection', name)
        self.check(all(p.get('type') in ('content', 'terminal') for p in parsed['objects']), 'client_packet_type', name)
        content = ''.join(p['content'] for p in observed if isinstance(p.get('content'), str))
        first, start, end = client.get('first_content_ns'), client.get('started_ns'), client.get('ended_ns')
        timing = type(start) is int and type(end) is int and start <= end
        if content:
            self.check(type(first) is int and timing and start <= first <= end, 'client_first_content', name)
        else:
            self.check(first is None, 'client_first_content', name)
        slo = (first - start <= 1000000000 and end - start <= 3000000000) if content and type(first) is int and timing and start <= first <= end else None
        normal = lambda value: ''.join(value.split())
        quality = (normal(content) == normal(case['expected_text']) and terminal == 'completed' and finish == 'stop') if content and isinstance(case.get('expected_text'), str) else None
        return dict(case_id=name, request_id=case['request_id'], route=case['route'], stratum=case['stratum'],
                    tenant_id=row.get('tenant_id') or 'unknown', planned_tenant=case['tenant'], eligible=case['eligible'], terminal=terminal, cache=row.get('cache'),
                    generation_count=len(row['attempts']), protocol=protocol, quality=quality, slo=slo,
                    first_content_ms=(first - start) / 1000000 if content and type(first) is int and timing else None,
                    end_ms=(end - start) / 1000000 if timing else None, joint=False)

    def caches(self, gateway):
        by_id = {r.get('request_id'): r for r in gateway}
        for r in gateway:
            if r.get('cache') != 'hit':
                continue
            name, origin = r.get('case_id'), r.get('cache_origin')
            good = isinstance(origin, dict)
            if not good:
                self.check(False, 'cache_origin', name)
                continue
            src = by_id.get(origin.get('request_id'), {})
            attempts = src.get('attempts', [])
            aid = origin.get('attempt_id')
            a = next((a for a in attempts if a.get('attempt_id') == aid), {})
            good = (bool(a) and src.get('terminal') == 'completed' and a.get('outcome') == 'completed'
                    and a.get('finish') == 'stop' and src.get('cache') == 'miss'
                    and src.get('tenant_id') == r.get('tenant_id') and src.get('policy') == r.get('policy')
                    and src.get('identity') == r.get('identity') and src.get('input_body') == r.get('input_body')
                    and src.get('cache_key') == r.get('cache_key') == origin.get('key')
                    and isinstance(r.get('cache_key'), str) and bool(r.get('cache_key'))
                    and src.get('sent_content') == r.get('sent_content')
                    and origin.get('content_sha256') == _sha(src.get('sent_content', ''))
                    and origin.get('usage') == a.get('usage') and _valid_usage(origin.get('usage'))
                    and src.get('clock_domain') == r.get('clock_domain')
                    and src.get('ended_ns', -1) <= r.get('started_ns', -1))
            self.check(good, 'cache_origin', name)

    def resources(self):
        obj = self.load('resources.json')
        self.check(isinstance(obj.get('clock_domain'), str) and bool(obj['clock_domain']), 'resource_clock', 'resource')
        intervals = obj.get('intervals', [])
        cleanup = self.load('cleanup.json')
        self.check(cleanup.get('all_reaped') is True and cleanup.get('ports') == {'8027': False, '8127': False}, 'resource_cleanup', 'cleanup')
        self.check(isinstance(cleanup.get('model_files_unchanged'), dict) and set(cleanup['model_files_unchanged']) >= {'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'config.json'} and all(v is True for v in cleanup['model_files_unchanged'].values()), 'model_cleanup', 'cleanup')
        processes = []
        self.check(isinstance(intervals, list) and {r.get('component') for r in intervals} == {'backend', 'gateway'}, 'resource_components', 'resource')
        for interval in intervals:
            component = interval.get('component')
            usage = obj.get('cpu', {}).get(component, {})
            processes.append(dict(pid=interval.get('pid'), component=component, started_ns=interval.get('started_ns'), ended_ns=interval.get('exited_ns'),
                                  ready_intervals=[[interval.get('ready_ns'), interval.get('stop_requested_ns')]],
                                  exited=type(interval.get('returncode')) is int,
                                  rusage=dict(ru_utime=usage.get('user_seconds'), ru_stime=usage.get('system_seconds'))))
        self.check(set(cleanup.get('owned_pids', [])) == {p['pid'] for p in processes}, 'resource_pids', 'cleanup')
        if not self.check(isinstance(processes, list) and bool(processes) and all(isinstance(p, dict) for p in processes), 'resource_schema', 'resource'):
            return None
        occupied, ready, cpu = [], [], []
        pids = set()
        for p in processes:
            pid = p.get('pid')
            self.check(type(pid) is int and pid > 0 and pid not in pids, 'resource_pid', 'resource')
            pids.add(pid)
            self.check(p.get('clock_domain', obj.get('clock_domain')) == obj.get('clock_domain'), 'resource_clock', str(pid))
            self.check(p.get('exited') is True, 'resource_reap', str(pid))
            if self.time_bounds(p, str(pid)):
                occupied.append([p['started_ns'], p['ended_ns']])
            intervals = p.get('ready_intervals', [])
            if not self.check(isinstance(intervals, list), 'resource_ready', str(pid)):
                intervals = []
            for interval in intervals:
                valid = (isinstance(interval, list) and len(interval) == 2 and all(type(x) is int for x in interval)
                         and type(p.get('started_ns')) is int and type(p.get('ended_ns')) is int
                         and p['started_ns'] <= interval[0] <= interval[1] <= p['ended_ns'])
                if self.check(valid, 'resource_ready', str(pid)):
                    ready.append(interval)
            usage = p.get('rusage')
            good = isinstance(usage, dict) and all(type(usage.get(k)) in (float, int) and math.isfinite(usage[k]) and usage[k] >= 0 for k in ('ru_utime', 'ru_stime'))
            if self.check(good, 'resource_rusage', str(pid)):
                cpu.append(usage['ru_utime'] + usage['ru_stime'])
        def union(intervals):
            result, end = 0, -1
            for start, stop in sorted(intervals):
                result += max(0, stop - max(start, end))
                end = max(end, stop)
            return result
        return dict(process_union_ns=union(occupied), ready_union_ns=union(ready),
                    supervisor_clock_domain=obj.get('clock_domain'), cpu_reaped_seconds=sum(cpu) if len(cpu) == len(processes) else None,
                    cpu_scope='reaped process rusage; may include startup and idle CPU',
                    gpu_kernel_seconds=None, gpu_weight_residency_seconds=None, tenant_gpu_seconds=None, paid_currency=None)

    def guarded(self, label, operation):
        try:
            return operation()
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError) as exc:
            self.check(False, 'row_schema', label, exc)
            return None

    def run(self):
        plan = self.load('plan.json')
        gateway, clients, backend, health = [self.load(name, rows=True) for name in ('gateway.jsonl', 'clients.json', 'backend.jsonl', 'health.json')]
        cases = self.audit_plan(plan)
        self.guarded('provenance', lambda: self.provenance(plan, gateway))
        g = self.unique(gateway, 'case_id', 'gateway')
        c = self.unique(clients, 'case_id', 'clients')
        expanded = []
        for step in health:
            names = step.get('case_ids')
            if self.check(isinstance(names, list) and all(isinstance(n, str) for n in names), 'health_schema', 'health'):
                expanded.extend({**step, 'case_id': n} for n in names)
        h = self.unique(expanded, 'case_id', 'health')
        self.unique(gateway, 'request_id', 'gateway')
        self.unique(clients, 'request_id', 'clients')
        for indexed, label, rows in ((g, 'gateway', gateway), (c, 'clients', clients), (h, 'health', expanded)):
            self.check(set(indexed) == set(cases) and len(rows) == 42, 'case_coverage', label)
        policies, policy = {}, 'rule-v1'
        for step in plan.get('steps', []):
            policy = step.get('policy', policy)
            for name in step.get('cases', []):
                policies[name] = policy
        for name, case in cases.items():
            state = h.get(name, {}).get('state', {})
            self.check(state.get('active') == 0 and state.get('workers') == 0 and state.get('reserved') == 0, 'not_quiescent', name)
            if name in g and name in c:
                self.guarded(name, lambda: self.request(case, g[name], c[name], policies.get(name)))
        burst = [r for r in gateway if r.get('stratum') == 'burst']
        self.check(len(burst) == 6 and Counter(r.get('terminal') for r in burst) == {'completed': 2, 'admission_rejected': 4}, 'burst_contract', 'burst')
        self.guarded('cache', lambda: self.caches(gateway))
        backend_report = self.guarded('backend', lambda: self.backend(backend, gateway))
        resource = self.guarded('resource', self.resources)
        accepted = not self.errors
        for row in self.requests:
            row['evidence_valid'] = accepted
            row['joint'] = accepted and row['protocol'] is True and row['quality'] is True and row['slo'] is True
        metrics = None
        if accepted:
            metrics = dict(gpu=self.usage_metrics(self.ledger), resource=resource,
                           joint=self.counts(self.requests), joint_eligible=self.counts([r for r in self.requests if r['eligible']]),
                           by_route=self.groups('route'), by_stratum=self.groups('stratum'), by_tenant=self.groups('tenant_id'))
        report = dict(schema=1, experiment='exp27', accepted=accepted, planned=42, eligible=37,
                      expected_max_native_attempts=29, auditor_sha256=_sha(Path(__file__).read_bytes()),
                      frozen_source_sha256=plan.get('source_sha256', {}), errors=self.errors,
                      metrics=metrics, requests=self.requests, attempt_ledger=self.ledger, backend=backend_report,
                      resource=resource, observed=dict(gateway_rows=len(gateway), client_rows=len(clients), backend_rows=len(backend),
                      terminal_counts=dict(Counter(str(r.get('terminal')) for r in gateway))),
                      scope='Single GPU loopback experiment; known native-token subtotal is not total cost, kernel time, tenant GPU time or paid currency')
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        return report

    @staticmethod
    def usage_metrics(ledger):
        known = [a for a in ledger if _valid_usage(a.get('resource_usage'))]
        failed = [a for a in ledger if a.get('outcome') != 'completed']
        retry = [a for a in ledger if a.get('retry')]
        def subtotal(rows):
            valid = [a for a in rows if _valid_usage(a.get('resource_usage'))]
            return dict(attempts=len(rows), known_usage_attempts=len(valid), unknown_usage_attempts=len(rows) - len(valid),
                        **{'known_' + k: sum(a['resource_usage'][k] for a in valid) for k in TOKEN_FIELDS})
        return {**subtotal(ledger), 'failed': subtotal(failed), 'retry': subtotal(retry)}

    @staticmethod
    def counts(rows):
        result = dict(denominator=len(rows), joint_pass=sum(r['joint'] for r in rows))
        result['joint_rate'] = result['joint_pass'] / len(rows) if rows else None
        for field in ('protocol', 'quality', 'slo'):
            result[field] = dict(passed=sum(r[field] is True for r in rows), failed=sum(r[field] is False for r in rows), unknown=sum(r[field] is None for r in rows))
        return result

    def groups(self, field):
        return {str(key): self.counts([r for r in self.requests if r.get(field) == key]) for key in sorted({r.get(field) for r in self.requests}, key=str)}

    def backend(self, rows, gateway):
        http_rows = [r for r in rows if r.get("component") == "backend-http" or ("sse" in r and "attempt_id" in r)]
        indexed = self.unique(http_rows, "attempt_id", "backend-http")
        attempts = {a["attempt_id"]: a for r in gateway for a in r.get("attempts", []) if isinstance(a, dict) and a.get("mode") == "gpu" and "attempt_id" in a}
        expected = set(attempts)  # Every planned GPU attempt needs independent evidence.
        self.check(set(indexed) == expected, "backend_coverage", "backend-http")
        for aid, row in indexed.items():
            attempt = attempts.get(aid)
            if not self.check(attempt is not None, "backend_unknown_attempt", str(aid)):
                continue
            self.check(row.get("request_id") == attempt.get("request_id"), "backend_request_id", str(aid))
            self.check(row.get("status") == attempt.get("http_status"), "backend_status", str(aid))
            body, sse = row.get("body"), row.get("sse")
            self.check(isinstance(body, str) and row.get("request_sha256") == _sha(body), "backend_request_hash", str(aid))
            self.check(isinstance(sse, str) and row.get("response_sha256") == _sha(sse), "backend_response_hash", str(aid))
            try:
                self.check(_json(body) == attempt.get("backend_body"), "backend_body", str(aid))
            except (ValueError, TypeError):
                self.check(False, "backend_body", str(aid))
            self.check(attempt.get("backend_body_sha256") == _sha(_canonical(attempt.get("backend_body"))), "gateway_backend_body_hash", str(aid))
            self.check(isinstance(sse, str) and sse.startswith(attempt.get("raw_sse", "")), "backend_response_prefix", str(aid))
            native = parse_native_sse(sse)
            self.check(not native["errors"], "backend_native_sse", str(aid), native["errors"])
            self.time_bounds(row, str(aid) + ":backend-http")
            for entry in self.ledger:
                if entry["attempt_id"] == aid:
                    entry["backend_http_usage"] = native["usage"]
                    backend_usage = native["usage"]
                    gateway_usage = entry["usage"]
                    if backend_usage is not None and _valid_usage(backend_usage):
                        entry.update(resource_usage=backend_usage, resource_usage_source="backend_http")
                        self.check(gateway_usage == backend_usage, "usage_reconciliation", str(aid),
                                   "backend has valid usage; gateway settlement is missing or differs")
            for field, value in (("request_b64", body), ("response_b64", sse)):
                if field in row:
                    try:
                        decoded = base64.b64decode(row[field], validate=True)
                        self.check(decoded == value.encode("utf-8"), "backend_base64", str(aid), field)
                    except (ValueError, TypeError, AttributeError):
                        self.check(False, "backend_base64", str(aid), field)
            if "send_returned_b64" in row:
                try:
                    returned = base64.b64decode(row["send_returned_b64"], validate=True)
                    self.check(sse.encode("utf-8").startswith(returned), "backend_send_prefix", str(aid))
                except (ValueError, TypeError, AttributeError):
                    self.check(False, "backend_send_prefix", str(aid))
        # Engine hooks have a separate evidence domain. Never promote HTTP close
        # or worker_joined to engine cancellation; the hook schema is independent.
        report = dict(http_rows=len(http_rows), http_evidence="checked" if http_rows else "absent_optional",
                    engine_abort_evidence="unknown", non_http_rows=len(rows) - len(http_rows),
                    scope="HTTP transport evidence does not establish engine abort or GPU kernel stop")
        if any(r.get("schema") == "exp27.backend.v1" or "engine_request_ids" in r for r in rows):
            report.update(self.native_backend(rows, indexed, attempts))
        else:
            self.check(not expected,
                       "native_evidence_required", "backend", "formal GPU attempts require native hooks")
            self.check(len(http_rows) == len(rows), "unsupported_backend_schema", "backend")
        return report

    def native_backend(self, rows, http, attempts):
        """CPU hooks, mapping and scheduler observations; no kernel-stop inference.

        Compare timestamps only inside the same backend clock domain. Native
        request overlap is reported separately from sequential gateway workers.
        """
        initial_errors = len(self.errors)
        installed = [r for r in rows if r.get("event") == "hooks_installed"]
        self.check(len(installed) == 1, "native_hooks", "backend")
        install = installed[0] if installed else {}
        self.check(install.get("installed") is True and install.get("vllm_version") == "0.8.5", "native_version", "backend")
        needed = {"AsyncLLMEngine.add_request", "AsyncLLMEngine.abort", "AsyncLLMEngine._abort",
                  "RequestTracker.abort_request", "RequestTracker.process_request_output", "LLMEngine.abort_request",
                  "LLMEngine.step", "_AsyncLLMEngine.step_async", "AsyncLLMEngine.engine_step"}
        self.check(needed <= set(install.get("hooks", [])), "native_hooks", "backend")
        domain, previous_ns = install.get("clock_domain"), -1
        supported = {"hooks_installed", "http_started", "http_request_chunk", "http_response_start", "http_response_chunk",
                     "http_disconnect", "http_send_raised", "http_finished", "engine_request", "engine_child_request",
                     "engine_output", "engine_finished", "add_returned", "add_raised", "abort_called", "abort_returned",
                     "abort_raised", "abort_done", "state_before", "state_after"}
        by_attempt, bindings, http_ids = {}, {}, {}
        for i, row in enumerate(rows):
            aid, event = row.get("attempt_id"), row.get("event")
            self.check(row.get("schema") == "exp27.backend.v1", "native_schema", str(aid))
            self.check(row.get("clock_domain") == domain and isinstance(domain, str), "native_clock", str(aid))
            self.check(row.get("pid") == install.get("pid"), "native_pid", str(aid))
            ns = row.get("backend_monotonic_ns")
            self.check(type(ns) is int and ns >= previous_ns, "native_event_order", str(aid))
            if type(ns) is int: previous_ns = ns
            self.check(row.get("audit_errors", 0) == 0, "native_audit_errors", str(aid))
            self.check(event in supported, "native_observation_error", str(aid), event)
            if aid is None:
                self.check(event == "hooks_installed", "native_identity", "backend", event)
                continue
            if not self.check(aid in attempts, "native_unknown_attempt", str(aid)):
                continue
            self.check(row.get("request_id") == attempts[aid].get("request_id"), "native_request_id", str(aid))
            identity = http.get(aid, {})
            self.check(row.get("http_id") == identity.get("http_id") and isinstance(row.get("http_id"), str), "native_http_id", str(aid))
            by_attempt.setdefault(aid, []).append((i, row))
            eid = row.get("engine_request_id")
            if event in ("engine_request", "engine_child_request"):
                if self.check(isinstance(eid, str) and bool(eid), "native_engine_id", str(aid)):
                    self.check(eid not in bindings, "native_duplicate_binding", str(aid), eid)
                    bindings[eid] = aid
            if event == "http_started":
                hid = row.get("http_id")
                self.check(hid not in http_ids, "native_duplicate_http", str(aid))
                http_ids[hid] = aid
        engine_attempts, starts, clears = [], {}, {}
        for aid, attempt in attempts.items():
            events = by_attempt.get(aid, [])
            h = http.get(aid, {})
            start_events = [(i, r) for i, r in events if r.get("event") == "http_started"]
            self.check(len(start_events) == 1 and h.get("event") == "http_finished", "native_http_lifecycle", aid)
            roots = [(i, r) for i, r in events if r.get("event") == "engine_request"]
            engine_ids = h.get("engine_request_ids", [])
            self.check(isinstance(engine_ids, list) and len(engine_ids) == len(set(engine_ids)) == 1,
                       "native_http_engine_ids", aid)
            self.check(len(roots) == 1 and [r.get("engine_request_id") for _, r in roots] == engine_ids, "native_engine_binding", aid)
            for _, r in events:
                if "engine_request_id" in r:
                    self.check(bindings.get(r["engine_request_id"]) == aid, "native_engine_owner", aid)
            if roots:
                starts[aid] = roots[0][1]["backend_monotonic_ns"]
                self.check(bool(start_events) and start_events[0][0] < roots[0][0], "native_bind_order", aid)
            finished = [r for _, r in events if r.get("event") == "engine_finished" and r.get("finished") is True]
            called = [(i, r) for i, r in events if r.get("event") == "abort_called"]
            returned = [(i, r) for i, r in events if r.get("event") == "abort_returned" and r.get("error") is None]
            for _, r in returned:
                self.check(any(x.get("hook") == r.get("hook") and x.get("engine_request_id") == r.get("engine_request_id")
                               and x["backend_monotonic_ns"] <= r["backend_monotonic_ns"] for _, x in called), "native_abort_order", aid)
            for _, r in called:
                self.check(any(x.get("hook") == r.get("hook") and x.get("engine_request_id") == r.get("engine_request_id")
                               and x["backend_monotonic_ns"] >= r["backend_monotonic_ns"] for _, x in returned), "native_abort_return", aid)
            abort_done = [r for _, r in events if r.get("event") == "abort_done"]
            for r in abort_done:
                self.check(any(x.get("hook") == r.get("hook") and x["backend_monotonic_ns"] <= r["backend_monotonic_ns"] for _, x in returned), "native_abort_done", aid)
            snapshots = [r for _, r in events if r.get("event") == "state_after" and r.get("snapshot_complete") is True]
            clean = []
            for r in snapshots:
                queues, cached, tracker = r.get("queues"), r.get("cached"), r.get("tracker")
                if not self.check(isinstance(queues, list) and isinstance(cached, list) and (tracker is None or isinstance(tracker, dict)), "native_state_schema", aid):
                    continue
                scheduler_pending = any(q.get("unfinished") is True for q in queues)
                engine_pending = scheduler_pending or any(q.get("remaining_steps", 0) > 0 for q in cached)
                self.check(r.get("scheduler_unfinished") is scheduler_pending and r.get("engine_pending_or_unfinished") is engine_pending, "native_state_flags", aid)
                if isinstance(tracker, dict):
                    self.check(set(tracker) == {"active_stream", "new_pending", "abort_pending"} and all(type(v) is bool for v in tracker.values()), "native_tracker", aid)
                    self.check(r.get("pending_or_unfinished") is (engine_pending or any(tracker.values())), "native_pending_flags", aid)
                if (r.get("pending_or_unfinished") is False and not engine_pending and isinstance(tracker, dict)
                        and not any(tracker.values()) and r.get("error") is None):
                    clean.append(r)
            quiescent = bool(snapshots) and bool(clean) and snapshots[-1] in clean
            self.check(quiescent, "native_not_quiescent", aid)
            if attempt.get("outcome") == "completed":
                self.check(bool(finished), "native_finish_missing", aid)
            else:
                self.check(bool(finished) or bool(called) and bool(returned), "native_abort_missing", aid)
            terminal_ns = max([r["backend_monotonic_ns"] for _, r in returned] + [r["backend_monotonic_ns"] for r in finished] + [-1])
            clean_after = [r for r in clean if r["backend_monotonic_ns"] >= terminal_ns]
            self.check(bool(clean_after), "native_final_snapshot", aid)
            if clean_after:
                clears[aid] = clean_after[0]["backend_monotonic_ns"]
            engine_attempts.append(dict(attempt_id=aid, engine_request_ids=engine_ids, http_id=h.get("http_id"),
                                        engine_finished=bool(finished), abort_called=bool(called),
                                        abort_returned=bool(returned), abort_done_observed=bool(abort_done),
                                        scheduler_quiescent=quiescent, gpu_kernel_stopped="unknown"))
        overlap = []
        for aid in attempts:
            if aid.endswith("/a2"):
                previous = aid[:-1] + "1"
                overlap.append(dict(previous_attempt_id=previous, attempt_id=aid,
                                    previous_engine_quiescent_before_next=(clears[previous] <= starts[aid])
                                    if previous in clears and aid in starts else None,
                                    evidence="same backend monotonic clock; CPU scheduler/tracker only"))
        for item in overlap:
            self.check(item["previous_engine_quiescent_before_next"] is True, "native_retry_overlap", item["attempt_id"])
        return dict(engine_abort_evidence="checked_cpu_hooks" if len(self.errors) == initial_errors else "invalid_cpu_hooks",
                    engine_attempts=engine_attempts, native_retry_order=overlap, gpu_kernel_stopped="unknown")



def analyze(out, summary_path=None):
    return _Audit(out, summary_path).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args()
    report = analyze(args.out, args.summary)
    print(json.dumps(dict(accepted=report['accepted'], errors=len(report['errors']), summary=str(args.summary or args.out / 'summary.json'))))
    return 0 if report['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
