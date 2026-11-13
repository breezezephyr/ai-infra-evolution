"""Trace/usage mutations must fail instead of manufacturing successful tenant bills."""
import copy,json,hashlib,pytest
import analyze

RAW='data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}}\n\ndata: [DONE]\n\n'
CLIENT_RAW='data: {"id":"r1","choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: {"id":"r1","choices":[],"gateway_usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9},"cache":"miss"}\n\ndata: [DONE]\n\n'
BODY={'model':'exp25-qwen3-0.6b','messages':[{'role':'user','content':'hi'}]}
REQUEST={'model':'lab-qwen','messages':[{'role':'user','content':'hi'}],'stream':True,'max_tokens':16}

def fixture():
 plan={'cases':[{'case_id':'c1','token':'lab-a','body':REQUEST,'status':200,'terminals':['delivered']}]}
 request_raw=json.dumps(REQUEST,sort_keys=True,separators=(',',':')).encode();bodyraw=json.dumps(BODY,sort_keys=True,separators=(',',':')).encode()
 client=[{'case_id':'c1','request_id':'r1','status':200,'request_sha256':hashlib.sha256(request_raw).hexdigest(),'raw':CLIENT_RAW,'started_ns':1,'first_content_ns':2,'ended_ns':3}]
 usage={'prompt_tokens':7,'completion_tokens':2,'total_tokens':9}
 gw=[{'case_id':'c1','request_id':'r1','tenant_id':'tenant-a','client_body_sha256':hashlib.sha256(request_raw).hexdigest(),'terminal':'delivered','http_status':200,'cache':'miss','cache_key':'key','policy_version':'v1','route_version':'r1','identity':{'model':'fixture'},'generation_usage':usage,'gateway_emitted_utf8_bytes':2,'gateway_emitted_sha256':hashlib.sha256(b'OK').hexdigest(),'clock_domain':'gw1','started_ns':1,'ended_ns':9,'events':[{'event':e,'monotonic_ns':i+1} for i,e in enumerate(['capability_accepted','cache_miss','admission_entered','route_selected','backend_first_content','backend_completed','review_allowed','client_first_content','terminal'])],
 'attempts':[{'attempt_id':'a1','request_id':'r1','tenant_id':'tenant-a','backend_body':BODY,'backend_body_sha256':hashlib.sha256(bodyraw).hexdigest(),'http_status':200,'usage_raw':usage,'usage':usage,'usage_source':'backend_stream_usage','response_sse_sha256':hashlib.sha256(RAW.encode()).hexdigest(),'finish_reason':'stop','generated_utf8_bytes':2,'generated_sha256':hashlib.sha256(b'OK').hexdigest(),'started_ns':3,'ended_ns':5}]}]
 backend=[{'attempt_id':'a1','request_id':'r1','status':200,'request_sha256':hashlib.sha256(bodyraw).hexdigest(),'body':bodyraw.decode(),'response_sha256':hashlib.sha256(RAW.encode()).hexdigest(),'sse':RAW,'clock_domain':'backend','started_ns':1,'first_body_ns':2,'ended_ns':3}]
 return plan,client,gw,backend


def test_complete_trace_settles_only_native_attempt_usage():
 report=analyze.audit(*fixture())
 assert report['accepted'] and report['planned']==1 and report['matched_requests']==1
 assert report['known_total_tokens']==9 and report['unknown_usage_attempts']==0
 assert report['tenant_usage']['tenant-a']['total_tokens']==9


def test_missing_duplicate_or_corrupt_evidence_retains_plan_denominator():
 for which in ('missing_backend','duplicate_client','wrong_tenant','wrong_wire_hash','wrong_native_usage','missing_done'):
  p,c,g,b=fixture()
  if which=='missing_backend':b=[]
  elif which=='duplicate_client':c.append(copy.deepcopy(c[0]))
  elif which=='wrong_tenant':g[0]['tenant_id']='tenant-b'
  elif which=='wrong_wire_hash':b[0]['request_sha256']='wrong'
  elif which=='wrong_native_usage':g[0]['attempts'][0]['usage_raw']={'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}
  elif which=='missing_done':c[0]['raw']=c[0]['raw'].replace('data: [DONE]\n\n','')
  r=analyze.audit(p,c,g,b)
  assert not r['accepted'] and r['planned']==1 and r['failed_requests']>=1


def test_empty_usage_is_unknown_and_never_replaced_with_text_length():
 p,c,g,b=fixture()
 raw=RAW.replace(',"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}','')
 b[0].update(sse=raw,response_sha256=hashlib.sha256(raw.encode()).hexdigest())
 a=g[0]['attempts'][0];a.update(usage_raw=None,usage=None,usage_source='unknown',response_sse_sha256=hashlib.sha256(raw.encode()).hexdigest())
 g[0]['generation_usage']=None
 c[0]['raw']=c[0]['raw'].replace('"gateway_usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}','"gateway_usage":null')
 r=analyze.audit(p,c,g,b)
 assert r['unknown_usage_attempts']==1 and r['known_total_tokens']==0


def test_unreconciled_evidence_cannot_publish_success_totals():
 p,c,g,b=fixture();b[0]['request_sha256']='wrong'
 r=analyze.audit(p,c,g,b)
 assert r['matched_requests']+r['failed_requests']==r['planned']
 assert r['known_total_tokens'] is None and r['tenant_usage']=={}
 p,c,g,b=fixture();c.append(copy.deepcopy(c[0]))
 r=analyze.audit(p,c,g,b)
 assert r['matched_requests']==0 and r['failed_requests']==1


def real_fixture():
 from pathlib import Path
 r=Path(__file__).resolve().parents[1]/'results/exp25/formal-v1'
 def lines(name):return [json.loads(x) for x in (r/name).read_text().splitlines()]
 return json.loads((r/'plan.json').read_text()),json.loads((r/'clients.json').read_text()),lines('gateway.jsonl'),lines('backend.jsonl')


@pytest.mark.parametrize('names',[['review-0','review-1'],['burst-0-0']],ids=['blocked-cost-erased','delivered-source-erased'])
def test_erased_blocked_generation_or_delivered_miss_cannot_settle_zero(names):
 p,c,g,b=real_fixture();removed=set()
 for row in g:
  if row['case_id'] in names:
   removed.update(a['attempt_id'] for a in row['attempts']);row.update(attempts=[],generation_usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},usage_source='no_generation_attempt')
 b=[row for row in b if row['attempt_id'] not in removed]
 result=analyze.audit(p,c,g,b)
 assert not result['accepted'] and result['planned']==42 and result['known_total_tokens'] is None


@pytest.mark.parametrize('fault',['usage','request_id','finish'])
def test_client_usage_id_and_finish_each_must_match_the_real_trace(fault):
 p,c,g,b=real_fixture()
 row=next(r for r in c if r['case_id']==('burst-0-0' if fault=='finish' else 'a-repeat'))
 if fault=='usage':row['raw']=row['raw'].replace('"total_tokens": 0','"total_tokens": 999')
 elif fault=='request_id':row['raw']=row['raw'].replace(row['request_id'],'wrong-request')
 else:row['raw']=row['raw'].replace('"finish_reason": "length"','"finish_reason": "stop"')
 result=analyze.audit(p,c,g,b)
 assert not result['accepted'] and result['known_total_tokens'] is None


def test_request_id_reuse_cannot_silently_overwrite_a_request_join():
 p,c,g,b=real_fixture()
 old=next(r['request_id'] for r in g if r['case_id']=='length-1');duplicate=next(r['request_id'] for r in g if r['case_id']=='length-0')
 for row in c:
  if row['request_id']==old:row['request_id']=duplicate;row['raw']=row['raw'].replace(old,duplicate)
 for row in g:
  if row['request_id']==old:
   row['request_id']=duplicate
   for attempt in row['attempts']:attempt['request_id']=duplicate
 for row in b:
  if row['request_id']==old:row['request_id']=duplicate
 result=analyze.audit(p,c,g,b)
 assert not result['accepted'] and result['known_total_tokens'] is None
