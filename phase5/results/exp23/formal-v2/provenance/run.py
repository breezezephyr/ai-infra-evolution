"""Freeze and execute synthetic CPU teaching experiments, never model calls."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import audit
import json
from pathlib import Path
import platform
import shutil
from replay import POLICIES


def make_traces():
    result=[]
    for length in (24,61):
        for name in ('all_correct_high','all_wrong_low','all_wrong_high','all_correct_low',
                     'alternating_calibrated','block_rejections','anti_calibrated','sparse_rejection'):
            mask=[];confidence=[]
            for i in range(length):
                if name.startswith('all_correct'):ok=True
                elif name.startswith('all_wrong'):ok=False
                elif name in ('alternating_calibrated','anti_calibrated'):ok=i%2==0
                elif name=='block_rejections':ok=i%7<5
                else:ok=i%11!=5
                if name.endswith('_high'):p=.99
                elif name.endswith('_low'):p=.1
                elif name=='anti_calibrated':p=.1 if ok else .99
                else:p=.99 if ok else .1
                mask.append(ok);confidence.append(p)
            result.append({'id':f'{name}-n{length}','scenario':name,'length':length,
                           'truth':list(range(1000,1000+length-1))+[0],
                           'correct':mask,'confidence':confidence})
    return result


def execute_cases(plan,replay_fn,toy_fn,validator=audit):
    by_trace={t['id']:t for t in plan['traces']};by_cost={c['id']:c for c in plan['costs']}
    def one(spec):
        t=by_trace[spec['trace']];cost=by_cost[spec['cost']]['points']
        value=replay_fn(t['truth'],t['correct'],t['confidence'],spec['policy'],cost)
        checks=validator.validate_replay(spec,t,cost,value)
        return {**value,'trace':spec['trace'],'cost':spec['cost'],'expected_policy':spec['policy'],
                'scenario':t['scenario'],'length':t['length'],'checks':checks,
                'status':'conformant' if all(checks.values()) else 'failed'}
    a_specs=[{**s,'expected_policy':s['policy']} for s in plan['replays']]
    records=validator.capture_cases(a_specs,one)
    def window(spec):
        value=toy_fn(plan['window_tokens'],**{k:spec[k] for k in ['window','backtrack','layers','keep']})
        valid=validator.validate_window(plan['window_tokens'],spec,value)
        # ID is recorder metadata, not a geometry input to the independent validator.
        return {**value,'representation_equal':value.get('mask')==value.get('compact'),
                'conformant':valid,'status':'conformant' if valid else 'failed','toy_status':value.get('status')}
    b_specs=[{**s,'id':f'b-{i:03d}'} for i,s in enumerate(plan['window_cases'])]
    # validate_window compares geometry, never untrusted identity fields.
    def checked_window(spec):
        geometry={k:spec[k] for k in ['window','backtrack','layers','keep']}
        return window(geometry)
    toy=validator.capture_cases(b_specs,checked_window)
    return records,toy


def load_snapshot(path):
    name='exp23_snapshot_'+path.stem
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).resolve().parent;provenance=out/'provenance';provenance.mkdir()
    for name in ('run.py','replay.py','window_toy.py','audit.py','设计.md','test_replay.py','test_window.py','test_audit.py'):
        shutil.copyfile(source/name,provenance/name)
    costs=[{'id':'setup_heavy','points':[800,100,25]},{'id':'draft_expensive','points':[200,100,300]},
           {'id':'linear_verify','points':[0,100,25]}]
    traces=make_traces()
    replays=[{'id':f"a-{i:03d}-{c['id']}-{policy}",'trace':t['id'],'cost':c['id'],'policy':policy}
             for i,t in enumerate(traces) for c in costs for policy in POLICIES]
    windows=[]
    for w in (2,4,8):
        for b in (0,1,3):
            for layers in (1,2,3):
                for keep in sorted({w+b-1,w+b,layers*(w-1)+1+b,64}):
                    windows.append({'window':w,'backtrack':b,'layers':layers,'keep':keep})
    plan={'revision':'formal-v2: explicit snapshot execution and independent audit; same synthetic inputs as v1',
          'scope':'synthetic CPU teaching replay; no inference, no DSpark implementation, no DeepInfer speed/quality measurement',
          'python':platform.python_version(),'commit_reading':'9bd9cf243fc53ef9afbf8f04d391d989117d6ab9',
          'cost_unit':'integer synthetic work points, not time; base + per-verification-position + per-draft',
          'candidate_rule':'longest prefix up to5 whose synthetic probability product>=0.8; not DeepInfer scheduling rule',
          'traces':traces,'costs':costs,'replays':replays,'window_tokens':list(range(1,65)),'window_cases':windows,
          'window_scope':'layered integer sums; no attention, position embeddings or model weights',
          'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(provenance.iterdir())}}
    text=json.dumps(plan,ensure_ascii=False,indent=2)+'\n';(out/'plan.json').write_text(text)
    # Read back the saved input, and execute the exact archived implementation files.
    plan=audit.read_frozen(out/'plan.json',text)
    for name,digest in plan['source_sha256'].items():
        if hashlib.sha256((provenance/name).read_bytes()).hexdigest()!=digest:raise ValueError('source snapshot mismatch')
    triples={(r['trace'],r['cost'],r['policy']) for r in plan['replays']}
    expected={(t['id'],c['id'],p) for t in plan['traces'] for c in plan['costs'] for p in POLICIES}
    if triples!=expected or len(triples)!=len(plan['replays']) or len({r['id'] for r in plan['replays']})!=len(plan['replays']):
        raise ValueError('frozen Cartesian matrix mismatch')
    frozen_replay=load_snapshot(provenance/'replay.py');frozen_toy=load_snapshot(provenance/'window_toy.py')
    frozen_audit=load_snapshot(provenance/'audit.py')
    assert Path(frozen_replay.run_trace.__code__.co_filename).resolve()==(provenance/'replay.py').resolve()
    assert Path(frozen_toy.compare.__code__.co_filename).resolve()==(provenance/'window_toy.py').resolve()
    records,toy=execute_cases(plan,frozen_replay.run_trace,frozen_toy.compare,frozen_audit)
    (out/'replays.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    (out/'window-cases.json').write_text(json.dumps(toy,ensure_ascii=False,indent=2)+'\n')
    matrix=[]
    for r in records:
        matrix.append({k:r.get(k) if k!='round_count' else len(r.get('rounds',[])) for k in
            ('id','scenario','length','cost','expected_policy','policy','status','round_count','draft_tokens',
             'accepted_draft_tokens','discarded_draft_tokens','verification_positions','work_points')})
    with (out/'replay-matrix.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    valid_toy=[r for r in toy if r['status']=='conformant']
    summary={'scope':plan['scope'],'revision':plan['revision'],
        'a':{'planned':len(replays),'statuses':dict(Counter(r['status'] for r in records)),
             'declared_checks_passed':sum(sum(r.get('checks',{}).values()) for r in records),
             'candidate_vs_fixed5':frozen_audit.pair_summary(records,[t['id'] for t in plan['traces']],[c['id'] for c in plan['costs']])},
        'b_toy':{'planned':len(windows),'statuses':dict(Counter(r['status'] for r in toy)),
             'conformant':len(valid_toy),'representation_equal':sum(r['representation_equal'] for r in valid_toy),
             'full_equal':sum(r['full_equal'] for r in valid_toy),
             'single_window_covered_but_full_differs':sum(r['single_window_covered'] and not r['full_equal'] for r in valid_toy)},
        'artifact_sha256':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in
                          ('plan.json','replays.json','window-cases.json','replay-matrix.csv')}}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    # Detect accidental source/plan changes during execution, without claiming authenticity.
    audit.read_frozen(out/'plan.json',text)
    for name,digest in plan['source_sha256'].items():
        if hashlib.sha256((provenance/name).read_bytes()).hexdigest()!=digest:raise ValueError('snapshot changed during execution')
    print(json.dumps(summary,ensure_ascii=False))
    if any(r['status']!='conformant' for r in records+toy):raise SystemExit(1)


if __name__=='__main__':main()
