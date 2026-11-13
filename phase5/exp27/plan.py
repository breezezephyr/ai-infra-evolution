"""Frozen ex-ante 42-request joint acceptance contract. No observed outcomes."""
import hashlib,json

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def make_plan():
 p={'experiment':'exp27','schema':1,'seed':27,'backend_port':8027,'gateway_port':8127,'active_limit':1,'waiting_limit':1,'prompt_limit':512,'slo':{'first_content_ms':1000,'complete_ms':3000},'cases':[],'steps':[], 'source_sha256':{},'scope':'single GPU; application response-cache cold/warm; loopback HTTP; controlled faults; no capacity/currency/kernel-time claim'}
 def case(name,route='integrated',tenant='tenant-a',prompt='只输出数字7。',expected='7',max_tokens=32,terminal='completed',attempts=1,eligible=True,**kw):
  body={'model':'lab-qwen','messages':[{'role':'user','content':prompt}],'max_tokens':max_tokens,'temperature':0,'seed':27,'stream':True}
  c={'case_id':name,'request_id':'exp27-'+name,'generation_id':'g0','idempotency_key':'safe-text-'+name,'mode':'gpu','route':route,'tenant':tenant,'token':'lab-a' if tenant=='tenant-a' else 'lab-b','body':body,'expected_text':expected,'eligible':eligible,'allowed_terminals':[terminal],'expected_attempts':attempts,'faults':[],'control':None,**kw}
  p['cases'].append(c);return c
 def seq(c,**kw):p['steps'].append({'cases':[c['case_id']],**kw})
 for tenant in ['tenant-a','tenant-b']:
  for rep in range(3):
   prefix=f'{tenant}-repeat{rep}'
   seq(case(prefix+'-direct',route='direct',tenant=tenant,stratum='normal-direct'),clear_cache=True)
   seq(case(prefix+'-cold',tenant=tenant,stratum='cache-cold',expected_cache='miss'))
   seq(case(prefix+'-warm',tenant=tenant,attempts=0,stratum='cache-warm',expected_cache='hit'))
 for task,expected in [('17+25','42'),('31-8','23'),('12*7','84')]:
  for route in ['direct','integrated']:seq(case('math-'+task+'-'+route,route=route,prompt=f'只输出算式{task}的整数结果，不要其他文字。',expected=expected,stratum='math'))
 c=case('reject-auth',terminal='authentication_rejected',attempts=0,eligible=False,stratum='entry-reject');c['token']='invalid';seq(c)
 c=case('reject-tools',terminal='capability_rejected',attempts=0,eligible=False,stratum='entry-reject');c['body']['tools']=[];seq(c)
 seq(case('reject-budget',prompt='hello '*800,terminal='budget_rejected',attempts=0,eligible=False,stratum='entry-reject'))
 seq(case('review-marker',prompt='请只输出字符串LAB_BLOCK，不要其他内容。',expected=None,terminal='review_rejected',eligible=False,stratum='review'))
 long='从1开始按顺序输出到100，用逗号分隔，不要省略，不要其他文字。'
 seq(case('truncated',prompt=long,expected=','.join(map(str,range(1,101))),max_tokens=2,stratum='truncated'))
 names=[]
 for i in range(6):
  c=case('burst-'+str(i),prompt=long+f'请求标记{i}。',expected=','.join(map(str,range(1,101))),max_tokens=96,stratum='burst',hold_seconds=.15)
  c.update(allowed_terminals=['completed','admission_rejected'],expected_attempts=None);names.append(c['case_id'])
 p['steps'].append({'cases':names,'burst':True})
 seq(case('retry-before-content',prompt='只输出1,2,3,4,5,6,7,8，不要其他文字。',expected='1,2,3,4,5,6,7,8',attempts=2,stratum='retry'))
 p['cases'][-1]['faults']=['pre_timeout',None]
 seq(case('break-after-commit',prompt='只输出1,2,3,4,5,6,7,8，不要其他文字。',expected='1,2,3,4,5,6,7,8',terminal='backend_error',stratum='delivery-fault',delivery_break=True),clear_cache=True)
 seq(case('client-cancel',prompt=long,expected=','.join(map(str,range(1,101))),max_tokens=192,terminal='client_disconnected',stratum='cancel',client_cancel=True),clear_cache=True)
 drain=case('drain-running',prompt=long,expected=','.join(map(str,range(1,101))),max_tokens=192,terminal='drain_timeout',stratum='drain')
 reject=case('drain-new-entry',terminal='draining',attempts=0,eligible=False,stratum='drain')
 p['steps'].append({'cases':[drain['case_id'],reject['case_id']],'drain':True,'clear_cache':True})
 seq(case('policy-change',stratum='identity-change',expected_cache='miss'),policy='rule-v2')
 seq(case('tenant-change',tenant='tenant-b',stratum='identity-change',expected_cache='miss'))
 assert len(p['cases'])==42
 p['quality']={'normalizer':'remove Unicode whitespace only','success':'exact expected_text and finish=stop, terminal completed; no answer is not quality success','eligible_requests':sum(c['eligible'] for c in p['cases'])}
 return p
