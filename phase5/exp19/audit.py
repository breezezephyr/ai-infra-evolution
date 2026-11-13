"""Outcome-aware accounting for an explicitly declared fixture matrix."""
from collections import Counter
import hashlib
import json
import math


def fact_equal(actual,expected):
    if isinstance(actual,bool) or isinstance(expected,bool):
        return type(actual) is type(expected) and actual==expected
    if actual is None or expected is None:
        return actual is None and expected is None
    if isinstance(actual,(int,float)) and isinstance(expected,(int,float)):
        return math.isclose(actual,expected,rel_tol=0,abs_tol=1e-6)
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(fact_equal(a,b) for a,b in zip(actual,expected))
    if isinstance(expected,dict):
        return isinstance(actual,dict) and actual.keys()==expected.keys() and all(fact_equal(actual[k],v) for k,v in expected.items())
    return type(actual) is type(expected) and actual==expected


def identity(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _contract_matches(case,row):
    return row is not None and row.get('contract_sha256')==identity(case)


def _check_states(row):
    checks=row.get('checks',[]);names=[check['name'] for check in checks]
    if len(names)!=len(set(names)):
        raise ValueError('duplicate result check name')
    return {check['name']:check.get('status','unknown') for check in checks}


def assess(case,row):
    if len(case['checks'])!=len(set(case['checks'])):
        raise ValueError('duplicate fixture check name')
    if row is None:
        return {'id':case['id'],'status':'unknown','reason':'missing result'}
    if not _contract_matches(case,row):
        return {'id':case['id'],'status':'unknown','reason':'missing/mismatched contract_sha256'}
    checks=_check_states(row)
    conversion=row.get('conversion',{}).get('status')
    if conversion not in {'ok','error'}:
        return {'id':case['id'],'status':'unknown','reason':'missing conversion outcome'}
    if conversion!=case['expect']['conversion']:
        return {'id':case['id'],'status':'fail','reason':'conversion outcome differs from frozen expectation'}
    states=[checks.get(tag,'unknown') for tag in case['checks']]
    if 'fail' in states:
        return {'id':case['id'],'status':'fail','reason':'contract assertion failed'}
    if not states or any(s!='pass' for s in states):
        return {'id':case['id'],'status':'unknown','reason':'requested check missing/unknown'}
    return {'id':case['id'],'status':'pass','reason':'all frozen checks satisfied'}


def summarize(cases,rows):
    ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)):
        raise ValueError('duplicate result id')
    case_ids=[c['id'] for c in cases]
    if len(case_ids)!=len(set(case_ids)) or not set(ids)<=set(case_ids):
        raise ValueError('duplicate/unexpected fixture id')
    by_id={r['id']:r for r in rows}
    outcomes=[assess(c,by_id.get(c['id'])) for c in cases]
    verified={c['id']:by_id[c['id']] for c in cases if _contract_matches(c,by_id.get(c['id']))}
    check_counts=Counter()
    for case in cases:
        found=_check_states(verified.get(case['id'],{}))
        for tag in case['checks']:
            check_counts[found.get(tag,'unknown')]+=1
    return dict(n=len(cases),accepted=sum(r.get('conversion',{}).get('status')=='ok' for r in verified.values()),
        rejected=sum(r.get('conversion',{}).get('status')=='error' for r in verified.values()),
        expected_rejections=sum(c['expect']['conversion']=='error' and verified.get(c['id'],{}).get('conversion',{}).get('status')=='error' for c in cases),
        unverified=len(rows)-len(verified),
        conformant=sum(o['status']=='pass' for o in outcomes),
        failed=sum(o['status']=='fail' for o in outcomes),unknown=sum(o['status']=='unknown' for o in outcomes),
        requested_check_count=sum(len(c['checks']) for c in cases),
        check_counts={s:check_counts[s] for s in ['pass','fail','unknown']},outcomes=outcomes)
