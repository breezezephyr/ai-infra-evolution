from copy import deepcopy
import json
import pytest
import audit
import replay
from run import make_traces


def sample():
    t=make_traces()[4]
    spec={'id':'a','trace':t['id'],'cost':'c','policy':'fixed5'}
    result=replay.run_trace(t['truth'],t['correct'],t['confidence'],'fixed5',[800,100,25])
    return spec,t,[800,100,25],result


def test_independent_check_rejects_mislabelled_baseline():
    spec,t,cost,r=sample()
    r=replay.run_trace(t['truth'],t['correct'],t['confidence'],'fixed0',cost)
    assert not all(audit.validate_replay(spec,t,cost,r).values())


def test_undercharging_early_rejection_is_detected_even_with_updated_totals():
    spec,t,cost,r=sample()
    for row in r['rounds']:
        row['verification_positions']=len(row['committed'])
        row['work_points']=cost[0]+cost[1]*row['verification_positions']+cost[2]*len(row['drafts'])
    r['verification_positions']=sum(x['verification_positions'] for x in r['rounds'])
    r['work_points']=sum(x['work_points'] for x in r['rounds'])
    assert not all(audit.validate_replay(spec,t,cost,r).values())


def test_exact_replay_passes_independent_audit():
    assert all(audit.validate_replay(*sample()).values())


def test_failed_pair_is_not_counted_as_lower_work():
    rows=[{'trace':'t','cost':'c','expected_policy':'fixed5','status':'conformant','work_points':20},
          {'trace':'t','cost':'c','expected_policy':'candidate','status':'failed','work_points':0}]
    r=audit.pair_summary(rows,['t'],['c'])[0]
    assert r['planned_pairs']==1 and r['valid_pairs']==0 and r['unavailable_pairs']==1
    assert r['candidate_lower_work']==r['equal_work']==r['candidate_higher_work']==0


def test_duplicate_pair_is_unavailable_instead_of_using_the_first_row():
    rows=[{'trace':'t','cost':'c','expected_policy':'fixed5','status':'conformant','work_points':20}]*2
    assert audit.pair_summary(rows,['t'],['c'])[0]['unavailable_pairs']==1


def test_saved_plan_drift_is_detected_before_execution(tmp_path):
    p=tmp_path/'plan.json';text=json.dumps({'truth':[1,0]});p.write_text(text.replace('1','2'))
    with pytest.raises(ValueError):audit.read_frozen(p,text)


def test_each_error_keeps_its_planned_slot_in_both_experiments():
    def bad(_):raise RuntimeError('controlled failure')
    rows=audit.capture_cases([{'id':str(i)} for i in range(3)],bad)
    assert len(rows)==3 and all(r['status']=='error' for r in rows)


def test_fake_equal_window_values_are_not_accepted():
    spec={'window':4,'backtrack':2,'layers':2,'keep':6}
    fake={**spec,'start':10,'query':13,'status':'compared','mask':0,'compact':0,'full':0,'full_equal':True,
          'single_window_covered':True,'dependency_covered':False}
    assert not audit.validate_window(list(range(1,17)),spec,fake)
