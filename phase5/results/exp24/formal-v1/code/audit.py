"""Independently reconcile frozen expected observations; never drop failed operations."""
from collections import Counter
import math


def classify(expected, observed):
    if observed.get('id') != expected['id'] or observed.get('op') != expected['op']:
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


def audit_records(plan, records):
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
    counts = Counter(outcomes.values())
    # Only conformant byte put/get/remove rows are included in descriptive timing.
    eligible = [r for r in records if outcomes[r['id']] == 'pass'
                and expected[r['id']].get('timing_group')
                and isinstance(r.get('latency_ms'), (float,int))
                and not isinstance(r.get('latency_ms'), bool)
                and math.isfinite(r['latency_ms']) and r['latency_ms'] >= 0]
    return {'planned':len(expected), **{k:counts[k] for k in ('pass','observed','fail','ambiguous','missing')},
            'accepted': counts['pass']+counts['observed'] == len(expected), 'outcomes':outcomes,
            'valid_latency_samples':len(eligible)}
