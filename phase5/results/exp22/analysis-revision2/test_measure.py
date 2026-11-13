import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
import measure
import hashlib
import json


def test_queue_rejects_overflow_and_releases_on_exception():
    gate = measure.Admission(active_limit=1, waiting_limit=1)
    first = gate.enter()
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(gate.enter)
        deadline = time.monotonic()+2
        while gate.snapshot()['waiting'] != 1 and time.monotonic() < deadline:
            time.sleep(.001)
        assert gate.snapshot() == {'active':1, 'waiting':1}
        with pytest.raises(measure.Overloaded):
            gate.enter()
        first.release()
        second = waiting.result(timeout=2)
        assert second.wait_ms > 0
        second.release()
        second.release()  # releasing twice must not increase capacity
    assert gate.snapshot() == {'active':0, 'waiting':0}


def test_simultaneous_calls_respect_active_cap():
    gate = measure.Admission(2, 10)
    peak = 0
    lock = threading.Lock()
    def work(_):
        nonlocal peak
        with gate.enter():
            with lock:
                peak = max(peak, gate.snapshot()['active'])
            time.sleep(.01)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(8)))
    assert peak == 2
    assert gate.snapshot() == {'active':0,'waiting':0}


def test_engine_durations_do_not_mix_client_and_backend_clocks():
    assert measure.engine_durations({'arrival_time':1000,'first_scheduled_time':1000.2,
        'first_token_time':1000.5,'finished_time':1001.5}) == pytest.approx(
        {'queue_ms':200,'first_token_ms':500,'scheduled_to_finish_ms':1300,'total_ms':1500})


def test_missing_or_failed_output_is_not_counted_as_consistent():
    rows=[{'id':'a','task':'x','status':200},{'id':'b','task':'x','status':429},
          {'id':'c','task':'x','status':200},{'id':'d','task':'x','status':200}]
    outputs={'a':{'token_ids':[1,2]},'d':{'token_ids':[1,3]}}
    report=measure.compare_outputs(rows,outputs)
    assert report == {'planned':4,'http_accepted':3,'with_token_ids':2,
                      'missing_token_ids':1,'compared_to_baseline':1,'equal':0,'different':1}


def test_empty_output_is_observed_but_not_silently_missing():
    rows=[{'id':'a','task':'x','status':200},{'id':'b','task':'x','status':200}]
    assert measure.compare_outputs(rows,{'a':{'token_ids':[]},'b':{'token_ids':[]}})['equal']==1


@pytest.mark.parametrize('mutation,issue', [('missing','engine_count'),('duplicate','engine_count'),
    ('hash','body_sha256'),('status','http_status')])
def test_reconciliation_detects_incomplete_or_wrong_evidence(mutation,issue):
    row={'id':'exp22-a','status':200,'body_sha256':'frozen'}
    gateway=[{'id':'exp22-a','status':200,'body_sha256':'frozen'}]
    backend=[{'event':'api_ingress','id':'exp22-a','body_sha256':'frozen'},
             {'event':'api_response','id':'exp22-a','status':200},
             {'event':'engine_finished','request_id':'chatcmpl-exp22-a','outputs':[{'token_ids':[1]}]}]
    if mutation=='missing':backend.pop()
    if mutation=='duplicate':backend.append(backend[-1])
    if mutation=='hash':backend[0]['body_sha256']='stale'
    if mutation=='status':backend[1]['status']=400
    assert issue in measure.reconcile(row,gateway,backend)


def test_reconciliation_accepts_exact_ids_and_hashes():
    row={'id':'exp22-a','status':200,'body_sha256':'frozen'}
    gateway=[dict(row)]
    backend=[{'event':'api_ingress',**row},{'event':'api_response',**row},
             {'event':'engine_finished','request_id':'chatcmpl-exp22-a','outputs':[{'token_ids':[1]}]}]
    assert measure.reconcile(row,gateway,backend)==[]


def strict_fixture():
    payload={'model':'frozen','temperature':0,'top_p':1,'top_k':-1,'seed':17,'max_tokens':32}
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    row={'id':'exp22-a','status':200,'body_sha256':digest,
         'response':{'id':'chatcmpl-exp22-a','model':'frozen','usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3},
                     'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}}
    config={'max_num_seqs':4}
    backend=[{'event':'api_ingress','id':row['id'],'body_sha256':digest},
        {'event':'api_response','id':row['id'],'status':200}, {'event':'api_finished','id':row['id']},
        {'event':'engine_request','request_id':'chatcmpl-exp22-a','settings':{**{k:payload[k] for k in ['temperature','top_p','top_k','seed','max_tokens']},'n':1},'effective_config':config.copy()},
        {'event':'engine_finished','request_id':'chatcmpl-exp22-a','prompt_token_ids':[7,8],
         'prompt_ids_sha256':hashlib.sha256(b'[7,8]').hexdigest(),
         'outputs':[{'token_ids':[9],'text':'ok','finish_reason':'stop'}]}]
    return row,[{k:row[k] for k in ['id','status','body_sha256']}],backend,payload,config


@pytest.mark.parametrize('mutation', ['response_id','prompt_usage','seed','config','duplicate_request','missing_finished','prompt_hash','plan_body'])
def test_strict_gate_rejects_mutated_evidence(mutation):
    row,gateway,events,payload,config=strict_fixture()
    if mutation=='response_id':row['response']['id']='stale'
    if mutation=='prompt_usage':row['response']['usage']['prompt_tokens']=42
    if mutation=='seed':events[3]['settings']['seed']=29
    if mutation=='config':events[3]['effective_config']['max_num_seqs']=8
    if mutation=='duplicate_request':events.append(events[3])
    if mutation=='missing_finished':events.pop(2)
    if mutation=='prompt_hash':events[-1]['prompt_token_ids']=[1,2]
    if mutation=='plan_body':payload['max_tokens']=96
    assert measure.validate_record(row,gateway,events,payload,config)


def test_strict_gate_accepts_complete_evidence():
    assert measure.validate_record(*strict_fixture())==[]


def test_bad_baseline_cannot_be_replaced_by_first_surviving_output():
    rows=[{'id':'a','task':'x','status':200},{'id':'b','task':'x','status':200}]
    r=measure.compare_outputs(rows,{'a':{'token_ids':[1]},'b':{'token_ids':[1]}},
                              verified_ids={'b'},baseline_ids={'x':'a'})
    assert r['http_accepted']==2 and r['evidence_verified']==1
    assert r['compared_to_baseline']==r['equal']==0 and r['missing_baseline']==1


def test_wall_clock_jump_is_flagged_without_modifying_token_evidence():
    assert measure.clock_discontinuity({'arrival_time':1000,'finished_time':1004.3},0,2_000_000_000)
    assert not measure.clock_discontinuity({'arrival_time':1000,'finished_time':1002},0,2_000_000_000)
