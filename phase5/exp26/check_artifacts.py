"""Final local artifact check. Historic experiment snapshots are never rewritten."""
from pathlib import Path
import json,hashlib,re,urllib.parse,subprocess,tempfile,datetime
ROOT=Path(__file__).resolve().parents[2];C=ROOT/'27-Phase5·8-半路抛锚';R=ROOT/'phase5/results/exp26';F=R/'formal-v1'
NODE='/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 paths=['phase5/README.md','phase5/大纲.md','phase5/实验计划.md','phase5/资料地图.md','phase5/资料输入.json','00-系列大纲.md','看板-推理服务化学习.html']
 docs=[ROOT/x for x in paths if x.endswith('.md')]+list((ROOT/'phase5/exp26').glob('*.md'))+[ROOT/'phase5/results/exp26-结论.md',C/'正文.md',C/'发布说明.md']
 broken=[];links=0
 for p in docs:
  assert not any(x in p.read_text() for x in ['__RESULTS__','__ENGINE__','__USAGE__']),p
  for target in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^)]+)\)',p.read_text()):
   target=target.strip('<>').split(' "')[0]
   if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
   links+=1;target=urllib.parse.unquote(target.split('#')[0]);target=re.sub(r':\d+$','',target)
   if not (p.parent/target).resolve().exists():broken.append({'file':str(p.relative_to(ROOT)),'target':target})
 assert not broken,broken
 plan=read(F/'plan.json');assert sha(F/'plan.json')==read(F/'freeze.json')['plan_sha256']
 for name,h in plan['source_sha256'].items():assert sha(F/'code'/name)==h,(name,'execution snapshot')
 assert read(F/'gateway-startup.json')['source_sha256']==plan['source_sha256']
 backend=read(R/'backend-startup.json');assert backend['source_sha256']['backend_audit.py']==plan['source_sha256']['backend_audit.py']
 assert read(F/'backend-snapshot.json')['model_identity_sha256']==sha(R/'model-identity.json')
 assert read(F/'backend-snapshot.json')['sha256']==sha(F/'backend.jsonl')
 s=read(F/'summary.json');assert s['accepted'] and s['planned']==17 and s['metrics']['matched_requests']==17
 assert s['metrics']['gpu']=={'attempts':6,'known_usage_attempts':2,'unknown_usage_attempts':4,'known_prompt_tokens':54,'known_completion_tokens':194,'known_total_tokens':248}
 assert s['metrics']['controlled']['attempts']==13 and s['metrics']['controlled']['known_total_tokens']==28
 cleanup=read(R/'cleanup.json');assert not cleanup['pid_exists'] and not any(cleanup['port_listening'].values()) and all(cleanup['model_files_unchanged'].values())
 gc=read(F/'gateway-cleanup.json');assert gc['exited'] and not gc['port_listening']
 tests=int(re.search(r'(\d+) passed',(R/'tests.txt').read_text()).group(1))
 mobile=read(C/'排版检查.json');assert mobile['pageWidth']==mobile['viewport']==390 and not mobile['unresolved'] and not mobile['literalBold']
 assert len(mobile['images'])==2 and all(i['width'] and i['height'] for i in mobile['images'])
 for name in ['00-封面','01-一页纸']:assert not read(C/'img'/f'{name}.layout.json')['issues']
 assert [i['phase'] for i in read(C/'img/00-封面.layout.json')['cover_stations'] if i['opacity']==1]==['5']
 scripts=re.findall(r'<script\b[^>]*>(.*?)</script>',(ROOT/'看板-推理服务化学习.html').read_text(),re.S)
 for script in scripts:
  with tempfile.NamedTemporaryFile(mode='w',suffix='.js') as f:
   f.write(script);f.flush();subprocess.run([NODE,'--check',f.name],capture_output=True,check=True)
 review=read(R/'independent-review.json');resolution=read(R/'review-resolution.json');assert resolution['unresolved_important']==0
 for directory in sorted(F.glob('analysis-revision*')):
  revision=read(directory/'manifest.json')
  for name,h in revision['source_sha256'].items():assert sha(directory/name)==h
 assert sha(ROOT/'phase5/exp26/analyze.py')==s['auditor_sha256']
 assert sha(F/'analysis-revision2/summary.json')==sha(F/'summary.json')
 checks={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'local_links':links,'broken':broken,'board_inline_scripts_checked':len(scripts),'mobile_width':390,'visual_inspection':'cover/card/evidence matrix/mobile first screen and usage section inspected','cover_station':'5 only','formal_source_hashes_verified':len(plan['source_sha256'])}
 info=read(ROOT/'phase5/资料输入.json');info['exp26_execution']['tests_passed']=tests
 info['exp26_execution']['cpu_tests'].update(passed=tests,final_count=tests)
 write(ROOT/'phase5/资料输入.json',info)
 planning=read(ROOT/'phase5/规划校验.json');planning.update(status=info['status'],completed_experiments=info['completed_experiments'],local_articles=info['completed_local_articles'],uploaded_articles=info['uploaded_articles'],pending_experiments=info['pending_experiments'],next='exp27 / P5.9 joint acceptance',exp26_execution=info['exp26_execution'],exp26_document_checks=checks)
 planning['artifacts']=[{'path':x,'sha256':sha(ROOT/x)} for x in paths];write(ROOT/'phase5/规划校验.json',planning)
 files={ROOT/x for x in paths+['phase5/规划校验.json','phase5/results/exp26-结论.md']}
 for base in [ROOT/'phase5/exp26',R,C]:files.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
 files.discard(C/'完成校验.json')
 complete={'date':'2026-10-26','status':'local experiment and article complete; not uploaded','uploaded':False,'mass_sent':False,
 'experiment':{'id':'exp26','formal':'formal-v1','requests':17,'attempts':19,'gpu_attempts':6,'native_known_tokens':248,'native_unknown_usage_attempts':4,'controlled_synthetic_known_tokens':28},'tests_passed':tests,'review':{'original':'phase5/results/exp26/independent-review.json','resolution':'phase5/results/exp26/review-resolution.json','rereview_performed':False},'layout':checks,'resources':cleanup,
 'artifacts':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]}
 write(C/'完成校验.json',complete);print(json.dumps({'artifacts':len(files),'links':links,'broken':len(broken),'tests':tests,'mobile_width':390}))
if __name__=='__main__':main()
