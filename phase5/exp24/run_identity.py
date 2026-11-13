"""Recheck the frozen identity-v1 metadata plan; no Store/model is called."""
import argparse,hashlib,json,pathlib,importlib.util

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--plan',default='phase5/results/exp24/identity-v1/plan.json');a=ap.parse_args()
 path=pathlib.Path(a.plan);p=json.loads(path.read_text());code=pathlib.Path(__file__).with_name('identity.py')
 assert hashlib.sha256(code.read_bytes()).hexdigest()==p['identity_code_sha256']
 spec=importlib.util.spec_from_file_location('identity',code);m=importlib.util.module_from_spec(spec)
 import sys;sys.modules['identity']=m;spec.loader.exec_module(m)
 base=m.CacheIdentity.from_mapping(p['base']);rows=[]
 for c in p['cases']:
  b=m.CacheIdentity.from_mapping({**p['base'],**({c['change']:c['value']} if c['change'] else {})})
  eligible=m.reuse_eligible(base,b,payload_hash_verified=True,importer_compatible=True)
  assert eligible==c['expected'];rows.append({'change':c['change'],'eligible':eligible,'key':b.cache_key()})
 print(json.dumps({'scope':p['scope'],'cases':len(rows),'matched':len(rows),'eligible':sum(r['eligible'] for r in rows)},ensure_ascii=False))
