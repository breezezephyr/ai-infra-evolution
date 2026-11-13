"""Read frozen plan/raw rows; recompute hashes and descriptive distributions."""
import pathlib,json,hashlib,statistics,argparse
from audit import audit_records,valid_latency


def summarize(out):
 p=json.loads((out/'plan.json').read_text());rows=[json.loads(x) for x in (out/'records.jsonl').read_text().splitlines()]
 for name,digest in p['code_sha256'].items():
  assert hashlib.sha256((out/'code'/name).read_bytes()).hexdigest()==digest
 # Do not trust the recorder's stored expected hash; regenerate from frozen seed/size.
 for c in p['cases']:
  if c['expected_kind']=='bytes':
   data=hashlib.shake_256(c['seed'].encode()).digest(c['size']) if 'seed' in c else b''
   assert hashlib.sha256(data).hexdigest()==c['sha256']
 events=json.loads((out/'lifecycle.json').read_text())
 client_pids={e['client']:e['pid'] for e in events if e['action']=='client_started'}
 audit=audit_records(p,rows,plan_sha256=hashlib.sha256((out/'plan.json').read_bytes()).hexdigest(),client_pids=client_pids);byid={r['id']:r for r in rows};groups={}
 for c in p['cases']:
  g=c.get('timing_group')
  if not g:continue
  groups.setdefault(g,{'planned':0,'valid':[],'failed':0,'invalid_timing':0})['planned']+=1
  if audit['outcomes'][c['id']]=='pass' and valid_latency(byid[c['id']].get('latency_ms')):groups[g]['valid'].append(byid[c['id']]['latency_ms'])
  elif audit['outcomes'][c['id']]!='pass':groups[g]['failed']+=1
  else:groups[g]['invalid_timing']+=1
 timings=[]
 for group,g in groups.items():
  v=g.pop('valid');size,op=group.split(':')
  timings.append({'size_bytes':int(size),'op':op,**g,'valid':len(v),'median_ms':statistics.median(v) if v else None,'min_ms':min(v) if v else None,'max_ms':max(v) if v else None})
 data_get=[c for c in p['cases'] if c.get('timing_group','').endswith(':get')]
 stage=[{'case':c,'observation':byid.get(c['id'])} for c in p['cases'] if c.get('stage')]
 dup=[{'case':c,'observation':byid.get(c['id'])} for c in p['cases'] if c.get('duplicate_variant')]
 result={'scope':p['scope'],'revision':p.get('revision'),'audit':{k:v for k,v in audit.items() if k!='outcomes'},
  'data_objects':len(data_get),'hash_matches':sum(audit['outcomes'][c['id']]=='pass' for c in data_get),
  'primary_data_get_clients':sorted({byid[c['id']]['client'] for c in data_get if audit['outcomes'][c['id']]=='pass'}),
  'timing_scope':'worker perf_counter_ns Store call only; put payload generated before timer; hash after timer; formal-v3 only',
  'timing_samples_per_size_op':10,'descriptive_only':True,'timings':timings,'duplicate_cases':dup,'lifecycle_observations':stage}
 (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('timings','duplicate_cases','lifecycle_observations')},ensure_ascii=False))
 return result

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();summarize(pathlib.Path(a.out))
