from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""Independent evidence reconciliation; no gateway implementation imports or token estimates."""
import json,hashlib,collections,pathlib,argparse,statistics

ZERO={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def digest(value):return hashlib.sha256(value).hexdigest()

def sse(text):
 content=[];finishes=[];usage=None;done=0;errors=[];ids=[];settlements=[]
 for event in text.split('\n\n'):
  payload='\n'.join(x[5:].lstrip(' ') for x in event.splitlines() if x.startswith('data:'))
  if not payload:continue
  if payload=='[DONE]':done+=1;continue
  if done:errors.append('after_DONE')
  try:o=json.loads(payload)
  except Exception:errors.append('bad_json');continue
  ids.append(o.get('id'))
  if 'gateway_usage' in o:settlements.append({'gateway_usage':o['gateway_usage'],'cache':o.get('cache')})
  if o.get('usage') is not None:usage=o['usage']
  for c in o.get('choices',[]):
   if c.get('delta',{}).get('content'):
    if finishes:errors.append('content_after_finish')
    content.append(c['delta']['content'])
   if c.get('finish_reason') is not None:finishes.append(c['finish_reason'])
 if done!=1 or len(finishes)!=1:errors.append('incomplete_or_duplicate_terminal')
 return {'content':''.join(content),'finish':finishes[-1] if finishes else None,'usage':usage,'errors':errors,'ids':ids,'settlements':settlements}

def normalize(value):
 if not isinstance(value,dict):return None
 if any(type(value.get(k)) is not int or value[k]<0 for k in ZERO):return None
 if value['prompt_tokens']+value['completion_tokens']!=value['total_tokens']:return None
 return {k:value[k] for k in ZERO}

def audit(plan,clients,gateways,backends):
 cases={c['case_id']:c for c in plan['cases']};issues={k:[] for k in cases};extra=[]
 def index(rows,key,label):
  found={}
  for row in rows:
   val=row.get(key)
   if val in found:
    extra.append(f'duplicate {label}: {val}')
   else:found[val]=row
  return found
 cr=index(clients,'case_id','client');gr=index(gateways,'case_id','gateway');br=index(backends,'attempt_id','backend')
 request_by_id=index(gateways,'request_id','gateway request ID');
 for row in gateways:
  if not isinstance(row.get('request_id'),str) or not row['request_id']:extra.append('missing gateway request ID')
 client_by_request=index(clients,'request_id','client request ID')
 attempt_ids=[];known_total=0;unknown=0;tenant_usage={};totals=collections.Counter();cache_counts=collections.Counter();intervals=[]
 client_times=[];backend_first_times=[];wait_times=[];cross_tenant=0
 if len(cases)!=len(plan['cases']):extra.append('duplicate planned case')
 for seen,label in ((cr,'client'),(gr,'gateway')):
  for key in seen:
   if key not in cases:extra.append(f'unplanned {label}: {key}')
 for key,c in cases.items():
  bad=issues[key];client=cr.get(key);g=gr.get(key)
  if client is None or g is None:bad.append('missing client/gateway');continue
  tenant={'lab-a':'tenant-a','lab-b':'tenant-b'}.get(c['token'])
  if client.get('request_id')!=g.get('request_id'):bad.append('request_id mismatch')
  if g.get('tenant_id')!=tenant:bad.append('tenant mismatch')
  if client.get('status')!=g.get('http_status'):bad.append('HTTP status mismatch')
  if c.get('status') is not None and client.get('status')!=c['status']:bad.append('unexpected HTTP status')
  if g.get('terminal') not in c['terminals']:bad.append('unexpected terminal')
  if c.get('cache') is not None and g.get('cache')!=c['cache']:bad.append('unexpected cache branch')
  wire=c.get('raw_body','').encode() if 'raw_body' in c else raw(c['body'])
  if client.get('request_sha256')!=digest(wire):bad.append('client frozen input mismatch')
  if g.get('client_body_sha256') is not None and g['client_body_sha256']!=digest(wire):bad.append('gateway input mismatch')
  events=g.get('events',[]);names=[e['event'] for e in events];times=[e['monotonic_ns'] for e in events]
  if names.count('terminal')!=1 or times!=sorted(times):bad.append('event order/terminal invalid')
  if not g.get('started_ns',1)<=g.get('ended_ns',0):bad.append('gateway clock invalid')
  if times and (times[0]<g['started_ns'] or times[-1]>g['ended_ns']):bad.append('event outside gateway clock')
  totals[g.get('terminal')]+=1;cache_counts[g.get('cache')]+=1
  attempts=g.get('attempts',[])
  if len(attempts)>1:bad.append('unplanned retries')
  terminal=g.get('terminal');cache_branch=g.get('cache')
  needs_attempt=terminal in ('review_rejected','backend_error','backend_incomplete') or (terminal=='delivered' and cache_branch=='miss')
  if needs_attempt and len(attempts)!=1:bad.append('terminal requires one generation attempt')
  if terminal=='delivered' and cache_branch not in ('hit','miss'):bad.append('delivered without cache/generation source')
  if cache_branch=='hit' and (terminal!='delivered' or attempts):bad.append('cache hit terminal/attempt invalid')
  if terminal in ('authentication_rejected','capability_rejected','encoding_rejected','budget_rejected','admission_rejected') and attempts:bad.append('pre-generation rejection has attempt')
  generation_events=('route_selected','backend_headers','backend_first_content','backend_completed')
  if not attempts and any(e in names for e in generation_events):bad.append('generation events without attempt')
  if attempts and (names.count('admission_entered')!=1 or names.count('route_selected')!=1):bad.append('attempt missing admission/route event')
  request_usage=dict(ZERO) if not attempts else None
  for a in attempts:
   aid=a['attempt_id'];attempt_ids.append(aid);b=br.get(aid)
   if b is None:bad.append('missing backend ingress');unknown+=1;continue
   if a.get('request_id')!=g['request_id'] or a.get('tenant_id')!=tenant or b.get('request_id')!=g['request_id']:bad.append('attempt correlation mismatch')
   canonical=digest(raw(a['backend_body']))
   if a.get('backend_body_sha256')!=canonical or b.get('request_sha256')!=canonical or digest(b.get('body','').encode())!=canonical:bad.append('backend wire body mismatch')
   if plan.get('backend_model'):
    expected={'model':plan['backend_model'],'messages':c['body']['messages'],'max_tokens':c['body']['max_tokens'],'temperature':0,'seed':25,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
    if a['backend_body']!=expected:bad.append('backend parameters differ from frozen request')
   if a.get('http_status')!=b.get('status'):bad.append('backend status mismatch')
   backend_text=b.get('sse','')
   if digest(backend_text.encode())!=b.get('response_sha256') or b.get('response_sha256')!=a.get('response_sse_sha256'):bad.append('backend response hash mismatch')
   parsed=sse(backend_text)
   if b.get('status')==200 and parsed['errors']:bad.append('backend SSE incomplete')
   if a.get('usage_raw')!=parsed['usage']:bad.append('raw usage mismatch')
   usage=normalize(parsed['usage']);request_usage=usage
   if a.get('usage')!=usage:bad.append('normalized usage mismatch')
   if usage is None:unknown+=1
   else:
    known_total+=usage['total_tokens'];counter=tenant_usage.setdefault(tenant,dict(ZERO))
    for k in ZERO:counter[k]+=usage[k]
   if a.get('finish_reason')!=parsed['finish']:bad.append('backend finish mismatch')
   if digest(parsed['content'].encode())!=a.get('generated_sha256') or len(parsed['content'].encode())!=a.get('generated_utf8_bytes'):bad.append('backend generated content mismatch')
   if g.get('prompt_tokens_computed') is not None and usage is not None and g['prompt_tokens_computed']!=usage['prompt_tokens']:bad.append('native template token count mismatch')
   if type(a.get('started_ns')) is not int or type(a.get('ended_ns')) is not int or a['ended_ns']<a['started_ns']:bad.append('attempt clock invalid')
   else:intervals.extend([(a['started_ns'],1,g['clock_domain']),(a['ended_ns'],-1,g['clock_domain'])])
  if g.get('generation_usage')!=request_usage:bad.append('request generation settlement mismatch')
  if g.get('cache')=='hit':
   origin=request_by_id.get(g.get('cache_origin_request_id'))
   if attempts or origin is None:bad.append('cache origin/attempt invalid')
   elif any(origin.get(field)!=g.get(field) for field in ('tenant_id','cache_key','policy_version','route_version','identity')):
    bad.append('illegal cache reuse');cross_tenant+=1
   else:
    oa=origin.get('attempts',[])
    if len(oa)!=1 or oa[0].get('attempt_id')!=g.get('cache_origin_attempt_id') or oa[0].get('finish_reason')!='stop' or 'cache_stored' not in [e['event'] for e in origin['events']]:bad.append('origin not a complete reviewed cached response')
    if g.get('cache_origin_usage')!=oa[0].get('usage_raw'):bad.append('origin usage mismatch')
  if client.get('status')==200:
   cp=sse(client.get('raw',''))
   if cp['errors']:bad.append('client SSE incomplete')
   if not cp['ids'] or any(value!=g['request_id'] for value in cp['ids']):bad.append('client SSE request ID mismatch')
   expected_settlement={'gateway_usage':g.get('generation_usage'),'cache':g.get('cache')}
   if cp['settlements']!=[expected_settlement]:bad.append('client SSE settlement mismatch')
   if digest(cp['content'].encode())!=g.get('gateway_emitted_sha256') or len(cp['content'].encode())!=g.get('gateway_emitted_utf8_bytes'):bad.append('client delivery mismatch')
   if c.get('finish') is not None and cp['finish']!=c['finish']:bad.append('unexpected finish')
   if c.get('expected_text') is not None and cp['content']!=c['expected_text']:bad.append('expected simple response mismatch')
   if attempts:
    if cp['finish']!=attempts[0].get('finish_reason'):bad.append('client/backend finish mismatch')
    parsed=sse(br[attempts[0]['attempt_id']]['sse']) if attempts[0]['attempt_id'] in br else None
    if parsed and cp['content']!=parsed['content']:bad.append('client/backend content mismatch')
    if 'review_allowed' not in names or 'client_first_content' not in names or names.index('review_allowed')>names.index('client_first_content'):bad.append('delivery before review')
   else:
    origin=request_by_id.get(g.get('cache_origin_request_id'))
    if origin and origin.get('attempts') and cp['finish']!=origin['attempts'][0].get('finish_reason'):bad.append('client/cache-origin finish mismatch')
    if origin and cp['content'] and origin.get('attempts') and digest(cp['content'].encode())!=origin['attempts'][0].get('generated_sha256'):bad.append('cached content mismatch')
   if type(client.get('first_content_ns')) is int and client['first_content_ns']>=client['started_ns']:
    client_times.append((client['first_content_ns']-client['started_ns'])/1e6)
  elif g.get('gateway_emitted_utf8_bytes')!=0:bad.append('rejected response emitted model content')
  if g.get('terminal')=='review_rejected' and 'LAB_BLOCK' in client.get('raw',''):bad.append('blocked content leaked')
  for e in events:
   if e['event']=='backend_first_content':backend_first_times.append((e['monotonic_ns']-g['started_ns'])/1e6)
  if isinstance(g.get('admission_wait_ms'),(int,float)):wait_times.append(g['admission_wait_ms'])
 if len(attempt_ids)!=len(set(attempt_ids)):extra.append('attempt id reused')
 if set(br)-set(attempt_ids):extra.append('unplanned backend ingress')
 # In one gateway clock domain these are call intervals, not GPU execution timelines.
 peaks={}
 for domain in {x[2] for x in intervals}:
  active=peak=0
  for _,delta,_ in sorted((x for x in intervals if x[2]==domain),key=lambda x:(x[0],x[1])):active+=delta;peak=max(active,peak)
  peaks[domain]=peak
 if plan.get('active_limit') is not None and any(x>plan['active_limit'] for x in peaks.values()):extra.append('generation admission overlap exceeded')
 for group in plan.get('burst_groups',[]):
  seen=[gr.get(x) for x in group['case_ids']]
  if not any(r and r['terminal']=='admission_rejected' for r in seen):extra.append('burst did not exercise overflow')
 failed=sum(bool(x) for x in issues.values())
 if extra:failed=len(plan['cases'])
 if failed:known_total=None;tenant_usage={}
 def distribution(values):return {'n':len(values),'median_ms':statistics.median(values) if values else None,'max_ms':max(values) if values else None}
 return {'planned':len(plan['cases']),'matched_requests':len(plan['cases'])-failed,
  'failed_requests':failed,'accepted':not failed and not extra,'issues':issues,'global_issues':extra,
  'terminal_counts':dict(totals),'cache_counts':dict(cache_counts),'attempts':len(attempt_ids),'known_total_tokens':known_total,
  'unknown_usage_attempts':unknown,'tenant_usage':tenant_usage,'illegal_cache_reuses':cross_tenant,
  'peak_gateway_attempt_intervals_by_clock_domain':peaks,'client_first_content':distribution(client_times),
  'gateway_receive_to_backend_first_content':distribution(backend_first_times),'admission_wait':distribution(wait_times),
  'scope':'one small GPU; buffered whole-response lab gate; exact response cache; no monetary billing, KV migration, semantic correctness or HA claim'}

def main(out):
 p=json.loads((out/'plan.json').read_text())
 for name,d in p['code_sha256'].items():
  if digest((out/'code'/name).read_bytes())!=d:raise ValueError('snapshot changed: '+name)
 startup=json.loads((out/'gateway-startup.json').read_text())
 if startup['source_sha256']!=p['code_sha256']:raise ValueError('running gateway snapshot mismatch')
 if not identity_valid(p['model_identity']):raise ValueError('invalid weight manifest')
 if startup['identity']['model_fingerprint']!=p['model_identity']['weights_sha256']:raise ValueError('running model identity mismatch')
 def lines(name):return [json.loads(x) for x in (out/name).read_text().splitlines() if x]
 result=audit(p,json.loads((out/'clients.json').read_text()),lines('gateway.jsonl'),lines('backend.jsonl'))
 (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('issues',)},ensure_ascii=False))
 if not result['accepted']:raise SystemExit(1)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();main(pathlib.Path(a.out))
