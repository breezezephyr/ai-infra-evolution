"""Independent plan/result audit and failure-denominator handling."""
from functools import lru_cache
import json
import math


def read_frozen(path,expected_text):
    text=path.read_text()
    if text!=expected_text:raise ValueError('persisted plan changed before execution')
    return json.loads(text)


def capture_cases(specs,execute):
    records=[]
    for spec in specs:
        try:
            value=execute(spec)
            records.append({**value,'id':spec['id']})
        except Exception as error:
            records.append({**spec,'status':'error','error':type(error).__name__+': '+str(error)})
    return records


def validate_replay(spec,trace,cost,result):
    checks={k:True for k in ('policy','draft_plan','cursor_and_commit','commit_categories',
                            'verification_budget','round_cost','aggregate_ledger','final_target')}
    try:
        truth=trace['truth'];mask=trace['correct'];conf=trace['confidence'];policy=spec['policy']
        checks['policy']=result['policy']==policy
        cursor=0;total_draft=total_accept=total_discard=total_verify=total_work=rejected=0;committed=[]
        for row in result['rounds']:
            remaining=len(truth)-cursor
            if remaining<=0:
                checks['cursor_and_commit']=False;break
            if policy=='candidate':
                feasible=[j for j in range(1,min(5,remaining)+1) if math.prod(conf[cursor:cursor+j])>=.8]
                length=max(feasible,default=0)
            else:length=min(int(policy[-1]),remaining)
            expected_draft=[truth[i] if mask[i] else truth[i]+100000 for i in range(cursor,cursor+length)]
            checks['draft_plan'] &= row['drafts']==expected_draft and row['synthetic_confidence']==conf[cursor:cursor+length]
            first_bad=next((j for j in range(length) if not mask[cursor+j]),length)
            count=first_bad+1 if first_bad<length else min(length+1,remaining)
            expected_commit=truth[cursor:cursor+count]
            checks['cursor_and_commit'] &= row['cursor']==cursor and row['next_cursor']==cursor+count and row['committed']==expected_commit
            categories={'accepted_draft_tokens':first_bad,'discarded_draft_tokens':length-first_bad,
                'correction_tokens':int(first_bad<length),'bonus_tokens':int(length>0 and first_bad==length and count>length),
                'target_direct_tokens':int(length==0)}
            checks['commit_categories'] &= all(row[k]==v for k,v in categories.items())
            verify=min(length+1,remaining);work=cost[0]+cost[1]*verify+cost[2]*length
            checks['verification_budget'] &= row['verification_positions']==verify
            checks['round_cost'] &= row['work_points']==work
            cursor+=count;committed.extend(expected_commit)
            total_draft+=length;total_accept+=first_bad;total_discard+=length-first_bad
            total_verify+=verify;total_work+=work;rejected+=int(first_bad<length)
        totals={'draft_tokens':total_draft,'accepted_draft_tokens':total_accept,
                'discarded_draft_tokens':total_discard,'verification_positions':total_verify,'work_points':total_work,'rejected_rounds':rejected}
        checks['aggregate_ledger']=all(result[k]==v for k,v in totals.items())
        checks['final_target']=cursor==len(truth) and committed==truth and result['committed']==truth
    except (KeyError,TypeError,ValueError,IndexError):return {k:False for k in checks}
    return checks


def pair_summary(rows,trace_ids,cost_ids):
    result=[]
    for cost in cost_ids:
        counts={'cost':cost,'planned_pairs':len(trace_ids),'valid_pairs':0,'unavailable_pairs':0,
                'candidate_lower_work':0,'equal_work':0,'candidate_higher_work':0}
        for trace in trace_ids:
            pair=[[r for r in rows if r['trace']==trace and r['cost']==cost and r['expected_policy']==p]
                  for p in ('fixed5','candidate')]
            if any(len(p)!=1 or p[0]['status']!='conformant' or 'work_points' not in p[0] for p in pair):
                counts['unavailable_pairs']+=1;continue
            counts['valid_pairs']+=1
            fixed,candidate=(p[0]['work_points'] for p in pair)
            counts['candidate_lower_work' if candidate<fixed else 'equal_work' if candidate==fixed else 'candidate_higher_work']+=1
        result.append(counts)
    return result


def validate_window(tokens,spec,result):
    try:
        n=len(tokens);w=spec['window'];depth=spec['layers'];start=max(0,n-spec['keep']);q=n-1-spec['backtrack']
        @lru_cache(None)
        def value(level,pos,left):
            if pos<left:return 0
            if level==0:return tokens[pos]
            return sum(value(level-1,j,left) for j in range(max(left,pos-w+1),pos+1))
        full=value(depth,q,0);trimmed=value(depth,q,start) if q>=start else None
        expected={**spec,'start':start,'query':q,'full':full,'mask':trimmed,'compact':trimmed,
            'status':'compared' if q>=start else 'query_evicted','full_equal':full==trimmed,
            'single_window_covered':start<=max(0,q-w+1),'dependency_covered':start<=max(0,q-depth*(w-1))}
        return all(result[k]==v for k,v in expected.items())
    except (KeyError,TypeError,ValueError,IndexError):return False
