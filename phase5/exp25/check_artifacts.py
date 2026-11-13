"""Validate this chapter's artifacts and update current manifests, preserving older snapshots."""
from pathlib import Path
import hashlib,json,re,datetime,subprocess,tempfile,urllib.parse
ROOT=Path(__file__).resolve().parents[2];C=ROOT/'26-Phase5·7-把站台接起来';R=ROOT/'phase5/results/exp25'
NODE='/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def main():
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 paths=['phase5/README.md','phase5/大纲.md','phase5/实验计划.md','phase5/资料地图.md','phase5/资料输入.json','00-系列大纲.md','看板-推理服务化学习.html']
 docs=[ROOT/x for x in paths if x.endswith('.md')]+list((ROOT/'phase5/exp25').glob('*.md'))+[ROOT/'phase5/results/exp25-结论.md',C/'正文.md',C/'发布说明.md']
 reports=[];broken=[]
 for p in docs:
  count=0
  for target in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^)]+)\)',p.read_text()):
   target=target.strip('<>').split(' "')[0]
   if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
   target=urllib.parse.unquote(target.split('#')[0]);target=re.sub(r':\d+$','',target);count+=1
   if not (p.parent/target).resolve().exists():broken.append({'source':str(p.relative_to(ROOT)),'target':target})
  reports.append({'file':str(p.relative_to(ROOT)),'local_links':count})
 assert not broken,broken
 legacy=read(R/'preflight/legacy-diagnostics-input.json')
 for s in legacy['sources'].values():assert sha(Path(s['source_path']))==s['sha256']
 plan=read(R/'formal-v1/plan.json')
 for name,d in plan['code_sha256'].items():assert sha(R/'formal-v1/code'/name)==d
 startup=read(R/'formal-v1/gateway-startup.json');assert startup['source_sha256']==plan['code_sha256']
 backend=read(R/'formal-v1/backend-snapshot.json');assert backend['backend_middleware_sha256']==plan['code_sha256']['backend_audit.py']
 assert backend['model_identity_sha256']==sha(R/'model-identity.json')
 summary=read(R/'formal-v1/summary.json');assert summary['accepted'] and summary['planned']==summary['matched_requests']==42
 assert summary['attempts']==12 and summary['known_total_tokens']==642 and summary['unknown_usage_attempts']==0
 cleanup=read(R/'cleanup.json');assert not cleanup['pid_exists'] and not any(cleanup['port_listening'].values()) and all(cleanup['model_files_unchanged'].values())
 mobile=read(C/'排版检查.json');assert mobile['pageWidth']==mobile['viewport']==390 and not mobile['unresolved'] and not mobile['literalBold']
 assert all(x['width'] and x['height'] for x in mobile['images'])
 for name in ['00-封面','01-一页纸']:assert not read(C/'img'/f'{name}.layout.json')['issues']
 assert [x['phase'] for x in read(C/'img/00-封面.layout.json')['cover_stations'] if x['opacity']==1]==['5']
 scripts=re.findall(r'<script\b[^>]*>(.*?)</script>',(ROOT/'看板-推理服务化学习.html').read_text(),re.S)
 for script in scripts:
  with tempfile.NamedTemporaryFile(mode='w',suffix='.js') as f:
   f.write(script);f.flush();subprocess.run([NODE,'--check',f.name],capture_output=True,check=True)
 review=read(R/'independent-review.json');resolution=read(R/'review-resolution.json')
 assert resolution['unresolved_important']==0
 tests=int(re.search(r'(\d+) passed',(R/'tests.txt').read_text()).group(1))
 checks={'checked_at':now,'local_links':sum(x['local_links'] for x in reports),'broken':broken,'files':reports,
  'legacy_source_hashes_verified':len(legacy['sources']),'formal_source_hashes_verified':len(plan['code_sha256']),
  'board_inline_scripts_checked':len(scripts),'mobile_width':390,'mobile_horizontal_overflow':False,
  'visual_inspection':'cover/card/scientific figure and mobile first screen/section 6 reviewed','cover_station':'5 only'}
 info=read(ROOT/'phase5/资料输入.json');info['exp25_execution']['regressions_passed']=tests;info['exp25_execution']['cpu_tests']={'passed':tests,'final_count':tests};info['exp25_execution']['native_usage'].pop('review_rejected_downstream_model_body_tokens',None);info['exp25_execution']['native_usage']['review_rejected_downstream_model_body_bytes']=0;write(ROOT/'phase5/资料输入.json',info)
 planning=read(ROOT/'phase5/规划校验.json');planning.update(status=info['status'],completed_experiments=info['completed_experiments'],
  local_articles=info['completed_local_articles'],uploaded_articles=info['uploaded_articles'],pending_experiments=info['pending_experiments'],
  next='exp26 / P5.8 cancellation, drain and safe retry',exp25_execution=info['exp25_execution'],exp25_document_checks=checks)
 planning['artifacts']=[{'path':x,'sha256':sha(ROOT/x)} for x in paths];write(ROOT/'phase5/规划校验.json',planning)
 files={ROOT/x for x in paths+['phase5/规划校验.json','phase5/results/exp25-结论.md']}
 for base in [ROOT/'phase5/exp25',R,C]:files.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
 files.update(Path(s['source_path']) for s in legacy['sources'].values());files.discard(C/'完成校验.json')
 complete={'date':'2026-10-26','status':'local experiment and article complete; not uploaded','uploaded':False,'mass_sent':False,
  'experiment':{'id':'exp25','formal':'formal-v1','requests':42,'generated_attempts':12,'cache_hits':7,'native_usage_tokens':642,
   'tenant_total_tokens':{'tenant-a':407,'tenant-b':235},'delivered':17,'length_deliveries':6,'review_rejected':2,'review_rejected_tokens':54},
  'tests':{'passed':tests,'evidence':'phase5/results/exp25/tests.txt'},
  'review':{'original':'phase5/results/exp25/independent-review.json','resolution':'phase5/results/exp25/review-resolution.json','rereview_performed':False},
  'layout':checks,'resources':cleanup,'scope':'one small Qwen GPU, two synthetic tenants; exact response cache, whole-response marker gate; no recipe-to-Qwen/DeepInfer/KV/HA/capacity/monetary billing claims',
  'progress':'P5.1-3 previously uploaded to draft box; P5.4-7 local only','next':'P5.8 / exp26',
  'artifacts':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]}
 write(C/'完成校验.json',complete)
 assert all(sha(ROOT/a['path'])==a['sha256'] for a in complete['artifacts'])
 print(json.dumps({'artifacts':len(complete['artifacts']),'local_links':checks['local_links'],'broken':len(broken),'tests':tests,'mobile_width':390},ensure_ascii=False))

if __name__=='__main__':main()
