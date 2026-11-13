"""Pack the exp27 replay material; dependencies/models remain explicit prerequisites."""
import pathlib,json,hashlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[2];D=ROOT/'phase5/exp27';R=ROOT/'phase5/results/exp27';C=ROOT/'28-Phase5·9-交班时拿什么说话'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def selected():
 result=[ROOT/'phase5/results/exp27-结论.md']
 for base in [D,R,C]:
  for p in base.rglob('*'):
   if not p.is_file() or p.is_symlink() or any(x in p.parts for x in ['__pycache__','.pytest_cache']):continue
   if p.name in ['完成校验.json','exp27-reproduce.tar.gz','exp27-reproduce.tar.gz.sha256','bundle-manifest.json','package-smoke.json']:continue
   if p.suffix=='.pyc':continue
   result.append(p)
 return sorted(set(result))
if __name__=='__main__':
 files=selected();manifest={'scope':'exp27 source/frozen plans/raw results/article/candidate only, not a backup of the entire series','prerequisites':'Linux vLLM0.8.5 env and Qwen3-0.6B model files with pinned hashes; candidate native repro also needs recipe0.2.0 wheel/tokenizer identified in contribution evidence','final_batch':'formal-v2','failed_run_retained':'formal-v1','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files]}
 m=R/'bundle-manifest.json';m.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');archive=R/'exp27-reproduce.tar.gz'
 with tarfile.open(archive,'w:gz') as tar:
  for p in files+[m]:tar.add(p,arcname=str(p.relative_to(ROOT)),recursive=False)
 digest=sha(archive);(R/'exp27-reproduce.tar.gz.sha256').write_text(digest+'  '+archive.name+'\n')
 with tarfile.open(archive) as tar:
  for member in tar.getmembers():
   assert not member.name.startswith('/') and '..' not in pathlib.PurePosixPath(member.name).parts
   if member.name.endswith('/bundle-manifest.json'):continue
   source=next(x for x in manifest['files'] if x['path']==member.name)
   assert hashlib.sha256(tar.extractfile(member).read()).hexdigest()==source['sha256']
 print(json.dumps({'files':len(files)+1,'bytes':archive.stat().st_size,'sha256':digest}))
