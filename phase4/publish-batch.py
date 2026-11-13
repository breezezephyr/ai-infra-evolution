"""Invoke the installed skill with scoped runtime compatibility and resumable receipts."""
import argparse
import json
import os
import hashlib
import re
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('mode',choices=['dry-run','upload'])
parser.add_argument('plan',type=Path)
parser.add_argument('--index',type=int,required=True)
args=parser.parse_args()
plan=json.loads(args.plan.read_text());row=plan['articles'][args.index];stage=Path(row['stage'])
env=os.environ.copy()
env['PATH']=str(args.plan.resolve().parent/'bin')+os.pathsep+env.get('PATH','')
command=['/home/researcher/.bun/bin/bun','--no-install','--no-env-file',
 '/home/researcher/.agents/skills/baoyu-post-to-wechat/scripts/wechat-api.ts',str(stage/'article.md'),
 '--theme',row['theme'],'--color',row['color'],'--title',row['title'],'--summary',row['summary'],'--cover',row['cover']]
if not row['external_links']:
    command.append('--no-cite')
if args.mode=='dry-run':
    command.append('--dry-run')
else:
    inventory=json.loads((args.plan.parent/'draft-inventory-before.json').read_text())
    if inventory['matches']:
        raise SystemExit('Existing Phase4 drafts found: do not duplicate; reconcile first.')
    if (stage/'upload-result.json').exists():
        raise SystemExit('Receipt already exists: read back rather than upload again.')
    if not (stage/'dry-run.json').exists():
        raise SystemExit('Missing reviewed dry-run result.')
    layout=json.loads((stage/'upload-layout.json').read_text())
    if not layout['passed']:
        raise SystemExit('Upload preview layout has unresolved errors.')
    expected=row['markdown_sha256']
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=expected for p in
           [Path(row['directory'])/'正文.md',stage/'article.md']):
        raise SystemExit('Markdown changed after preparation: review new content first.')
result=subprocess.run(command,cwd=Path.cwd(),env=env,capture_output=True,text=True,timeout=180)
(stage/f'{args.mode}.log').write_text(result.stderr)
if result.returncode:
    print(result.stderr[-2500:])
    raise SystemExit(result.returncode)
receipt=json.loads(result.stdout)
if args.mode=='upload' and not (receipt.get('success') and receipt.get('media_id')):
    raise SystemExit('Missing media_id: inspect logs/inventory before any retry.')
if args.mode=='upload':
    cover_id=re.search(r'Cover uploaded successfully, media_id: (\S+)',result.stderr)
    receipt['cover_media_id']=cover_id.group(1) if cover_id else None
    receipt['cover_sha256']=hashlib.sha256(Path(row['cover']).read_bytes()).hexdigest()
    receipt['markdown_sha256']=hashlib.sha256((stage/'article.md').read_bytes()).hexdigest()
(stage/('dry-run.json' if args.mode=='dry-run' else 'upload-result.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
