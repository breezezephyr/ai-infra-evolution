"""Verify targeted local artifacts and save current planning/completion hashes."""
from pathlib import Path
import json,hashlib,re,datetime,subprocess,tempfile,urllib.parse,sys
ROOT=Path(__file__).resolve().parents[2]
C=ROOT/'25-Phase5·6-行李不跟车走'
NODE='/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def main():
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 planpaths=['phase5/README.md','phase5/大纲.md','phase5/实验计划.md','phase5/资料地图.md','phase5/资料输入.json','00-系列大纲.md','看板-推理服务化学习.html']
 docs=[ROOT/x for x in planpaths if x.endswith('.md')]+list((ROOT/'phase5/exp24').glob('*.md'))+[ROOT/'phase5/results/exp24-结论.md',C/'正文.md',C/'发布说明.md']
 linkreports=[];broken=[]
 for path in docs:
  count=0
  for target in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^)]+)\)',path.read_text()):
   target=target.strip('<>').split(' "')[0]
   if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
   target=urllib.parse.unquote(target.split('#')[0]);target=re.sub(r':\d+$','',target)
   dest=(path.parent/target).resolve();count+=1
   if not dest.exists():broken.append({'source':str(path.relative_to(ROOT)),'target':target})
  linkreports.append({'file':str(path.relative_to(ROOT)),'local_links':count})
 assert not broken,broken
 source=read(ROOT/'phase5/vendor/exp24-source/Mooncake/source-manifest.json')
 for f in source['files']:assert sha(Path(f['local_path']))==f['sha256'],f['path']
 scripts=re.findall(r'<script\b[^>]*>(.*?)</script>',(ROOT/'看板-推理服务化学习.html').read_text(),re.S)
 for script in scripts:
  with tempfile.NamedTemporaryFile(suffix='.js',mode='w') as f:
   f.write(script);f.flush();subprocess.run([NODE,'--check',f.name],check=True,capture_output=True)
 mobile=read(C/'排版检查.json')
 assert mobile['pageWidth']==mobile['viewport'] and not mobile['unresolved'] and not mobile['literalBold']
 assert all(x['width']>0 and x['height']>0 for x in mobile['images'])
 for name in ['00-封面','01-一页纸']:
  layout=read(C/'img'/f'{name}.layout.json');assert not layout['issues']
 assert [x['phase'] for x in read(C/'img/00-封面.layout.json')['cover_stations'] if x['opacity']==1]==['5']
 summary=read(ROOT/'phase5/results/exp24/formal-v3/summary.json');assert summary['audit']['accepted']
 assert summary['data_objects']==summary['hash_matches']==40
 clean=read(ROOT/'phase5/results/exp24/formal-v3/cleanup-live.json');assert clean['all_closed']
 rereview=read(ROOT/'phase5/results/exp24/recorder-rereview.json')
 article=read(ROOT/'phase5/results/exp24/article-review.json')
 assert rereview.get('remaining_material_issues')==0
 if article.get('remaining_material_issues') is not None:assert article['remaining_material_issues']==0
 assert article.get('status') in ('passed','noissues','pass'),article.get('status')
 checks={'checked_at':now,'local_links':sum(x['local_links'] for x in linkreports),'broken':broken,'files':linkreports,
         'board_scripts_checked':len(scripts),'source_files_sha256_verified':len(source['files']),
         'mobile_width':mobile['viewport'],'mobile_horizontal_overflow':False,'cover_station':'5 only',
         'visual_inspection':'cover/card/scientific figure/mobile first screen and section 5 visually reviewed',
         'review_files':['phase5/results/exp24/recorder-rereview.json','phase5/results/exp24/article-review.json']}
 info=read(ROOT/'phase5/资料输入.json');planning=read(ROOT/'phase5/规划校验.json')
 planning.update(status=info['status'],completed_experiments=info['completed_experiments'],local_articles=info['completed_local_articles'],
                 uploaded_articles=info['uploaded_articles'],pending_experiments=info['pending_experiments'],next='exp25 / P5.7 gateway integration',
                 exp24_execution=info['exp24_execution'],exp24_document_checks=checks)
 planning['artifacts']=[{'path':x,'sha256':sha(ROOT/x)} for x in planpaths]
 write(ROOT/'phase5/规划校验.json',planning)
 # Include new experiment material, source subset, all retained revisions, chapter and current progress.
 files=set(ROOT/x for x in planpaths+['phase5/规划校验.json','phase5/results/exp24-结论.md'])
 for base in [ROOT/'phase5/exp24',ROOT/'phase5/results/exp24',ROOT/'phase5/vendor/exp24-source',C]:
  files.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
 files.discard(C/'完成校验.json')
 complete={'date':'2026-10-26','status':'local article and experiment complete; not uploaded','uploaded':False,'mass_sent':False,
  'experiment':{'id':'exp24','formal':'formal-v3','planned_api_operations':238,'assertion_pass':228,'observed_only':10,'failed':0,'missing':0,'primary_objects':40,'hash_matches':40,'identity_cases':12},
  'source':{'mooncake_commit':source['commit'],'source_version':'0.3.12.post1','executed_wheel':'0.3.13.post1 non-CUDA','binary_build_commit_verified':False,'archived_mooncake_files':len(source['files'])},
  'tests':{'passed':197,'evidence':'phase5/results/exp24/tests.txt'},'review':{'recorder':'phase5/results/exp24/recorder-rereview.json','article':'phase5/results/exp24/article-review.json'},
  'layout':checks,'resources':{'live_cleanup':'phase5/results/exp24/formal-v3/cleanup-live.json','all_own_pids_and_logged_ports_closed':True},
  'scope':'TCP-configured cross-process local Store API, payload branch/socket path untraced; no model/GPU/RDMA/PD; metadata/flags contract separate',
  'progress':'P5.1-3 previously uploaded to draft box; P5.4-6 local only','next':'P5.7 / exp25',
  'artifacts':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]}
 write(C/'完成校验.json',complete)
 assert all(sha(ROOT/f['path'])==f['sha256'] for f in complete['artifacts'])
 print(json.dumps({'artifacts':len(complete['artifacts']),'local_links':checks['local_links'],'broken':len(broken),'source_files':len(source['files']),'mobile_width':mobile['viewport']},ensure_ascii=False))

if __name__=='__main__':main()
