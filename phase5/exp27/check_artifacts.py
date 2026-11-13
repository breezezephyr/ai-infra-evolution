"""Current chapter completion and progress hashes; historical snapshots stay untouched."""
from pathlib import Path
import json,hashlib,re,urllib.parse,subprocess,tempfile,datetime
ROOT=Path(__file__).resolve().parents[2];C=ROOT/'28-Phase5·9-交班时拿什么说话';R=ROOT/'phase5/results/exp27';F=R/'formal-v2'
NODE='/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 paths=['phase5/README.md','phase5/大纲.md','phase5/实验计划.md','phase5/资料地图.md','phase5/资料输入.json','00-系列大纲.md','看板-推理服务化学习.html']
 docs=[ROOT/x for x in paths if x.endswith('.md')]+list((ROOT/'phase5/exp27').glob('*.md'))+[ROOT/'phase5/exp27/contribution/候选说明.md',ROOT/'phase5/results/exp27-结论.md',C/'正文.md',C/'发布说明.md']
 broken=[];links=0
 for p in docs:
  assert not any(x in p.read_text() for x in ['__RESULTS__','__USAGE__','__HANDOFF__']),p
  for target in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^)]+)\)',p.read_text()):
   target=target.strip('<>').split(' "')[0]
   if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
   links+=1;target=urllib.parse.unquote(target.split('#')[0]);target=re.sub(r':\d+$','',target)
   if not (p.parent/target).resolve().exists():broken.append({'file':str(p.relative_to(ROOT)),'target':target})
 assert not broken,broken
 plan=read(F/'plan.json');assert sha(F/'plan.json')==read(F/'freeze.json')['plan_sha256']
 for name,h in plan['source_sha256'].items():assert sha(F/'code'/name)==h
 assert read(F/'gateway-startup.json')['source_sha256']==plan['source_sha256']
 assert read(F/'backend-startup.json')['source_sha256']==plan['source_sha256']
 s=read(F/'summary.json');assert s['accepted'] and s['planned']==42 and s['eligible']==37
 assert s['metrics']['gpu']['attempts']==29 and s['metrics']['gpu']['known_total_tokens']==770 and s['metrics']['gpu']['unknown_usage_attempts']==3
 assert s['metrics']['joint_eligible']['joint_pass']==21 and s['metrics']['joint_eligible']['denominator']==37
 cleanup=read(F/'cleanup.json');assert cleanup['all_reaped'] and not any(cleanup['ports'].values()) and all(cleanup['model_files_unchanged'].values())
 assert not read(R/'formal-v1/summary.json')['accepted']
 tests=int(re.search(r'(\d+) passed',(R/'tests.txt').read_text()).group(1))
 mobile=read(C/'排版检查.json');assert mobile['pageWidth']==mobile['viewport']==390 and not mobile['unresolved'] and not mobile['literalBold']
 assert len(mobile['images'])==2 and all(i['width'] and i['height'] for i in mobile['images'])
 for name in ['00-封面','01-一页纸']:assert not read(C/'img'/f'{name}.layout.json')['issues']
 assert [i['phase'] for i in read(C/'img/00-封面.layout.json')['cover_stations'] if i['opacity']==1]==['5']
 scripts=re.findall(r'<script\b[^>]*>(.*?)</script>',(ROOT/'看板-推理服务化学习.html').read_text(),re.S)
 for script in scripts:
  with tempfile.NamedTemporaryFile(mode='w',suffix='.js') as f:
   f.write(script);f.flush();subprocess.run([NODE,'--check',f.name],capture_output=True,check=True)
 resolution=read(R/'review-resolution.json');assert resolution['unresolved_important']==0
 for d in sorted(F.glob('analysis-revision*')):
  m=read(d/'manifest.json')
  for name,h in m['source_sha256'].items():assert sha(d/name)==h
 assert sha(ROOT/'phase5/exp27/analyze.py')==s['auditor_sha256']
 manifest=read(R/'bundle-manifest.json')
 for item in manifest['files']:assert sha(ROOT/item['path'])==item['sha256'],item['path']
 assert sha(R/'exp27-reproduce.tar.gz')==(R/'exp27-reproduce.tar.gz.sha256').read_text().split()[0]
 checks={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'local_links':links,'broken':broken,'board_inline_scripts_checked':len(scripts),'mobile_width':390,'visual_inspection':'cover/card/evidence/mobile inspected','cover_station':'5 only','formal_source_hashes_verified':len(plan['source_sha256'])}
 info=read(ROOT/'phase5/资料输入.json');info['exp27_execution']['tests_passed']=tests;info['exp27_execution']['cpu_tests']={'passed':tests,'scope':'main gateway and auditor; recipe candidate selected checks separate'};write(ROOT/'phase5/资料输入.json',info)
 planning=read(ROOT/'phase5/规划校验.json');planning.update(status=info['status'],completed_experiments=info['completed_experiments'],local_articles=info['completed_local_articles'],uploaded_articles=info['uploaded_articles'],pending_experiments=info['pending_experiments'],next='P5.4-9 awaiting user upload instruction; migration/contribution candidate optional',exp27_execution=info['exp27_execution'],exp27_document_checks=checks)
 planning['artifacts']=[{'path':x,'sha256':sha(ROOT/x)} for x in paths];write(ROOT/'phase5/规划校验.json',planning)
 files={ROOT/x for x in paths+['phase5/规划校验.json','phase5/results/exp27-结论.md']}
 for base in [ROOT/'phase5/exp27',R,C]:files.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and p.suffix!='.pyc')
 files.discard(C/'完成校验.json')
 complete={'date':'2026-10-26','status':'local experiment and article complete; not uploaded','uploaded':False,'mass_sent':False,'experiment':{'id':'exp27','final':'formal-v2','requests':42,'eligible':37,'joint_pass':21,'attempts':29,'known_token_subtotal':770,'unknown_usage_attempts':3,'first_failed_run_retained':True},'tests_passed':tests,'review':{'original':'phase5/results/exp27/independent-review.json','resolution':'phase5/results/exp27/review-resolution.json','rereview_performed':False},'layout':checks,'resources':cleanup,'bundle':'phase5/results/exp27/exp27-reproduce.tar.gz','artifacts':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]}
 write(C/'完成校验.json',complete);print(json.dumps({'artifacts':len(files),'links':links,'broken':len(broken),'tests':tests,'mobile_width':390}))
if __name__=='__main__':main()
