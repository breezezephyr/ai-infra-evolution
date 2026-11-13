"""Unpack the built archive and run its CPU-only tests with this interpreter."""
from pathlib import Path
import hashlib,json,subprocess,sys,tarfile,tempfile
ROOT=Path(__file__).resolve().parents[2];R=ROOT/'phase5/results/exp27'
if __name__=='__main__':
 archive=R/'exp27-reproduce.tar.gz'
 with tempfile.TemporaryDirectory(prefix='exp27-portable-') as dest:
  with tarfile.open(archive) as t:t.extractall(dest,filter='data')
  d=Path(dest)/'phase5/exp27'
  p=subprocess.run([sys.executable,'-B','-m','pytest',str(d/'test_gateway.py'),str(d/'test_analyze.py'),str(d/'test_run.py'),'-q','-p','no:cacheprovider'],capture_output=True,text=True,cwd=dest)
  report={'scope':'portable unpack and CPU gateway/auditor/environment tests; no GPU or model calls','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
  (R/'package-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}));sys.exit(p.returncode)
