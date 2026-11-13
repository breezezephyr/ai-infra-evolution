"""Freeze and execute synthetic CPU teaching experiments, never model calls."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil
from replay import POLICIES, run_trace
from window_toy import compare


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


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).resolve().parent;provenance=out/'provenance';provenance.mkdir()
    for name in ('run.py','replay.py','window_toy.py','设计.md','test_replay.py','test_window.py'):
        shutil.copyfile(source/name,provenance/name)
    costs=[{'id':'setup_heavy','points':[800,100,25]},
           {'id':'draft_expensive','points':[200,100,300]},
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
    plan={'scope':'synthetic CPU teaching replay; no inference, no DSpark implementation, no DeepInfer speed/quality measurement',
          'python':platform.python_version(),'commit_reading':'9bd9cf243fc53ef9afbf8f04d391d989117d6ab9',
          'cost_unit':'integer synthetic work points, not time; base + per-verification-position + per-draft',
          'candidate_rule':'longest prefix up to5 whose synthetic probability product>=0.8; not DeepInfer scheduling rule',
          'traces':traces,'costs':costs,'replays':replays,
          'window_scope':'layered integer sums; no attention, position embeddings or model weights',
          'window_tokens':list(range(1,65)),'window_cases':windows,
          'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(provenance.iterdir())}}
    (out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    # The plan and executable snapshots are persisted before the first replay.
    by_trace={t['id']:t for t in traces};by_cost={c['id']:c for c in costs};records=[]
    for spec in replays:
        t=by_trace[spec['trace']];cost=by_cost[spec['cost']]['points']
        try:
            r=run_trace(t['truth'],t['correct'],t['confidence'],spec['policy'],cost)
            checks={'exact_committed_target':r['committed']==t['truth'],
                    'one_final_eos':r['committed'].count(0)==1 and r['committed'][-1]==0,
                    'draft_ledger':r['draft_tokens']==r['accepted_draft_tokens']+r['discarded_draft_tokens'],
                    'cost_ledger':r['work_points']==sum(cost[0]+cost[1]*x['verification_positions']+cost[2]*len(x['drafts']) for x in r['rounds']),
                    'progress':all(x['next_cursor']>x['cursor'] for x in r['rounds'])}
            records.append({**spec,**r,'scenario':t['scenario'],'length':t['length'],'checks':checks,
                            'status':'conformant' if all(checks.values()) else 'failed'})
        except Exception as error:
            records.append({**spec,'status':'error','error':type(error).__name__+': '+str(error)})
    toy=[]
    for i,spec in enumerate(windows):
        r=compare(plan['window_tokens'],**spec)
        r['id']=f'b-{i:03d}';r['representation_equal']=r['mask']==r['compact']
        r['conformant']=r['representation_equal'] and (not r['dependency_covered'] or r['full_equal'])
        toy.append(r)
    (out/'replays.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    (out/'window-cases.json').write_text(json.dumps(toy,ensure_ascii=False,indent=2)+'\n')
    matrix=[]
    for r in records:
        matrix.append({k:r.get(k) if k!='round_count' else len(r.get('rounds',[])) for k in
            ('id','scenario','length','cost','policy','status','round_count','draft_tokens','accepted_draft_tokens','discarded_draft_tokens','verification_positions','work_points')})
    with (out/'replay-matrix.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    groups=[]
    for c in costs:
        wins=ties=losses=0
        for t in traces:
            fixed=next(r for r in records if r['trace']==t['id'] and r['cost']==c['id'] and r['policy']=='fixed5')
            candidate=next(r for r in records if r['trace']==t['id'] and r['cost']==c['id'] and r['policy']=='candidate')
            if candidate['work_points']<fixed['work_points']:wins+=1
            elif candidate['work_points']==fixed['work_points']:ties+=1
            else:losses+=1
        groups.append({'cost':c['id'],'paired_traces':len(traces),'candidate_lower_work':wins,'equal_work':ties,'candidate_higher_work':losses})
    summary={'scope':plan['scope'],'a':{'planned':len(replays),'statuses':dict(Counter(r['status'] for r in records)),
             'declared_checks_passed':sum(sum(r.get('checks',{}).values()) for r in records),
             'candidate_vs_fixed5':groups},
             'b_toy':{'planned':len(windows),'conformant':sum(r['conformant'] for r in toy),
             'representation_equal':sum(r['representation_equal'] for r in toy),'full_equal':sum(r['full_equal'] for r in toy),
             'single_window_covered_but_full_differs':sum(r['single_window_covered'] and not r['full_equal'] for r in toy)},
             'artifact_sha256':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in ('plan.json','replays.json','window-cases.json','replay-matrix.csv')}}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))
    if any(r['status']!='conformant' for r in records) or not all(r['conformant'] for r in toy):raise SystemExit(1)


if __name__=='__main__':main()
