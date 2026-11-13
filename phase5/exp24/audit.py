"""Independently reconcile frozen expected observations; never drop failed operations."""
from collections import Counter
import math
import hashlib
import json


def request_for(case):
    ignored = {'expected_kind','code','sha256','timing_group','duplicate_variant'}
    request = {k:v for k,v in case.items() if k not in ignored}
    request.setdefault('stage','normal')
    return request


def request_digest(case):
    return hashlib.sha256(json.dumps(request_for(case),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def valid_latency(value):
    return type(value) in (float,int) and math.isfinite(value) and value >= 0


def classify(expected, observed):
    if observed.get('id') != expected['id'] or observed.get('op') != expected['op']:
        return 'fail'
    if 'client' in expected:
        if (observed.get('client') != expected['client'] or observed.get('stage') != expected.get('stage','normal')
            or observed.get('request_sha256') != request_digest(expected) or observed.get('key') != expected.get('key')
            or type(observed.get('pid')) is not int or observed['pid'] <= 0):
            return 'fail'
    if observed.get('complete') is not True:
        return 'fail'
    kind = expected['expected_kind']
    if kind == 'observation':
        return 'observed' if observed.get('kind') in ('bytes','code','none','exception') else 'fail'
    if kind == 'miss_or_error':
        return 'ambiguous' if observed.get('kind') == 'none' else 'fail'
    if kind != observed.get('kind'):
        return 'fail'
    if kind == 'bytes':
        return 'pass' if (observed.get('size') == expected['size'] and
                          observed.get('sha256') == expected['sha256']) else 'fail'
    if kind == 'code':
        return 'pass' if observed.get('value') == expected['code'] else 'fail'
    if kind == 'none':
        return 'pass'
    if kind == 'exception':
        return 'pass' if observed.get('exception_type') == expected['exception_type'] else 'fail'
    return 'fail'


def audit_records(plan, records, *, plan_sha256=None, client_pids=None):
    expected = {e['id']: e for e in plan['cases']}
    if len(expected) != len(plan['cases']):
        raise ValueError('duplicate plan id')
    seen = {}
    for record in records:
        key = record['id']
        if key in seen or key not in expected:
            raise ValueError('duplicate or unplanned record: '+key)
        seen[key] = record
    outcomes = {key: classify(case, seen[key]) if key in seen else 'missing'
                for key, case in expected.items()}
    for key, record in seen.items():
        if plan_sha256 is not None and (record.get('plan_sha256') != plan_sha256 or record.get('worker_sha256') != plan['code_sha256']['worker.py']):
            outcomes[key]='fail'
        if client_pids is not None and record.get('pid') != client_pids.get(expected[key].get('client')):
            outcomes[key]='fail'
    counts = Counter(outcomes.values())
    # Only conformant byte put/get/remove rows are included in descriptive timing.
    eligible = [r for r in records if outcomes[r['id']] == 'pass'
                and expected[r['id']].get('timing_group')
                and valid_latency(r.get('latency_ms'))]
    return {'planned':len(expected), **{k:counts[k] for k in ('pass','observed','fail','ambiguous','missing')},
            'accepted': counts['pass']+counts['observed'] == len(expected), 'outcomes':outcomes,
            'valid_latency_samples':len(eligible),
            'invalid_timing_samples':sum(1 for r in records if outcomes[r['id']]=='pass' and expected[r['id']].get('timing_group') and not valid_latency(r.get('latency_ms')))}
