"""Failure accounting and byte integrity are acceptance boundaries, not timing filters."""
import pytest
from audit import classify, audit_records


def test_bytes_hash_checks_not_just_get_return():
    expected = {'id':'read', 'op':'get', 'expected_kind':'bytes', 'sha256':'abc', 'size':4}
    good = {'id':'read','op':'get','complete':True,'kind':'bytes','sha256':'abc','size':4,'latency_ms':1}
    assert classify(expected, good) == 'pass'
    for patch in ({'sha256':'wrong'}, {'size':3}, {'complete':False}):
        assert classify(expected, {**good, **patch}) == 'fail'


def test_missing_none_is_observation_not_confirmed_miss():
    e = {'id':'m','op':'get','expected_kind':'miss_or_error'}
    assert classify(e, {'id':'m','op':'get','complete':True,'kind':'none','latency_ms':1}) == 'ambiguous'
    assert classify(e, {'id':'m','op':'get','complete':False,'kind':'timeout'}) == 'fail'


def test_integer_error_is_not_a_successful_write():
    e = {'id':'p','op':'put','expected_kind':'code','code':0}
    assert classify(e, {'id':'p','op':'put','complete':True,'kind':'code','value':-200}) == 'fail'


def test_unknown_and_missing_stay_in_plan_denominator():
    plan = {'cases':[{'id':'a','op':'put','expected_kind':'code','code':0},
                     {'id':'b','op':'get','expected_kind':'bytes','size':4,'sha256':'abc'}]}
    report = audit_records(plan, [{'id':'a','op':'put','complete':False,'kind':'timeout'}])
    assert report['planned'] == 2
    assert report['pass'] == 0 and report['fail'] == 1 and report['missing'] == 1
    assert report['valid_latency_samples'] == 0
    assert not report['accepted']


def test_duplicate_or_unplanned_ids_rejected():
    plan={'cases':[{'id':'a','op':'put','expected_kind':'code','code':0}]}
    row={'id':'a','op':'put','complete':True,'kind':'code','value':0,'latency_ms':1}
    with pytest.raises(ValueError): audit_records(plan,[row,row])
    with pytest.raises(ValueError): audit_records(plan,[{**row,'id':'other'}])


def test_exploratory_observation_is_separate_from_assertion_pass():
    plan={'cases':[{'id':'a','op':'get','expected_kind':'observation'}]}
    report=audit_records(plan,[{'id':'a','op':'get','complete':True,'kind':'bytes','size':0,'sha256':'abc','latency_ms':1}])
    assert report['observed']==1 and report['pass']==0 and report['accepted']


def correlated():
    from audit import request_digest
    e={'id':'a','op':'get','client':'B','key':'fixture','stage':'normal','expected_kind':'bytes','size':4,'sha256':'abc'}
    r={'id':'a','op':'get','client':'B','key':'fixture','stage':'normal','complete':True,'kind':'bytes','size':4,'sha256':'abc','pid':42,'request_sha256':request_digest(e)}
    return e,r


@pytest.mark.parametrize('patch',[{'client':'A'},{'stage':'fault'},{'key':'other'},{'request_sha256':'wrong'},{'pid':True}])
def test_request_correlation_mutations_rejected(patch):
    e,r=correlated()
    assert classify(e,r)=='pass'
    assert classify(e,{**r,**patch})=='fail'


def test_plan_and_snapshot_and_process_binding():
    e,r=correlated();p={'cases':[e],'code_sha256':{'worker.py':'code'}}
    r.update(plan_sha256='plan',worker_sha256='code')
    assert audit_records(p,[r],plan_sha256='plan',client_pids={'B':42})['accepted']
    for patch in ({'plan_sha256':'wrong'},{'worker_sha256':'wrong'},{'pid':43}):
        assert not audit_records(p,[{**r,**patch}],plan_sha256='plan',client_pids={'B':42})['accepted']


@pytest.mark.parametrize('value',[None,True,-1,float('inf'),float('nan')])
def test_bad_timings_stay_out_of_timing_denominator(value):
    from audit import valid_latency
    assert not valid_latency(value)
    e={'id':'a','op':'put','expected_kind':'code','code':0,'timing_group':'1:put'}
    r={'id':'a','op':'put','complete':True,'kind':'code','value':0,'latency_ms':value}
    a=audit_records({'cases':[e]},[r]);assert a['pass']==1 and a['valid_latency_samples']==0 and a['invalid_timing_samples']==1


def test_runner_rejects_failed_audit_after_saving_cleanup(tmp_path,monkeypatch):
    import json,runner
    p={'code_sha256':{},'package':'stub','version':'1','master_port':50240,'metrics_port':9024,'client_ports':[],
       'cases':[{'id':'missing','op':'get','expected_kind':'bytes','size':1,'sha256':'x'}],'steps':[]}
    (tmp_path/'plan.json').write_text(json.dumps(p))
    monkeypatch.setattr(runner.importlib.metadata,'version',lambda name:'1')
    monkeypatch.setattr(runner,'listening',lambda port:False)
    monkeypatch.setattr(runner.time,'sleep',lambda seconds:None)
    with pytest.raises(RuntimeError,match='audit acceptance failed'):runner.run(tmp_path)
    assert json.loads((tmp_path/'audit.json').read_text())['missing']==1
    assert (tmp_path/'cleanup.json').exists()
