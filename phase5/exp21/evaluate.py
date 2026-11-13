"""Independent strict JSON, schema and task oracle checks for exp21."""
import json
import math
from jsonschema import Draft202012Validator

def equal(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b

def strict_json(text):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('duplicate JSON key')
            out[k]=v
        return out
    def invalid(value):raise ValueError('non-finite JSON number: '+value)
    def number(value):
        n=float(value)
        if not math.isfinite(n):raise ValueError('non-finite JSON number')
        return n
    return json.loads(text,object_pairs_hook=pairs,parse_constant=invalid,parse_float=number)

def evaluate(content,schema,want,finish_reason='stop'):
    Draft202012Validator.check_schema(schema)
    r={'json_valid':False,'schema_valid':False,'business_correct':False,'complete':finish_reason=='stop','deliverable':False}
    try:value=strict_json(content)
    except (ValueError,TypeError) as exc:r['parse_error']=str(exc);return r
    r['json_valid']=True;r['value']=value
    errors=list(Draft202012Validator(schema).iter_errors(value));r['schema_valid']=not errors
    r['schema_errors']=[{'path':list(e.absolute_path),'message':e.message} for e in errors]
    r['business_correct']=equal(value,want)
    r['deliverable']=r['complete'] and r['schema_valid'] and r['business_correct']
    return r

def summarize(plan,rows):
    ids=[r['id'] for r in rows];pids=[p['id'] for p in plan]
    if len(ids)!=len(set(ids)) or len(pids)!=len(set(pids)) or not set(ids)<=set(pids):raise ValueError('duplicate/unexpected record')
    if len({p.get('run_id') for p in plan})>1:raise ValueError('mixed plan run_id')
    byid={r['id']:r for r in rows};valid=[byid[p['id']] for p in plan if p['id'] in byid and p.get('contract') and byid[p['id']].get('contract')==p['contract']
                                       and ('run_id' not in p or byid[p['id']].get('run_id')==p['run_id'])]
    result={'n':len(plan),'recorded_current_contract':len(valid),'missing_or_stale':len(plan)-len(valid),'accepted':sum(r.get('accepted') is True for r in valid),
            'rejected':sum(r.get('accepted') is False and r.get('http_status') is not None for r in valid),'transport_errors':sum(bool(r.get('transport_error')) for r in valid)}
    accepted=[r for r in valid if r.get('accepted') is True]
    for k in ['json_valid','schema_valid','business_correct','complete','deliverable']:
        result[k]=sum(r.get('evaluation',{}).get(k) is True for r in accepted)
        result[k+'_measured']=sum(isinstance(r.get('evaluation',{}).get(k),bool) for r in accepted)
    return result
