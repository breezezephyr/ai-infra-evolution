"""使用已安装的微信渲染器生成本地预览；不会调用上传接口。"""
from pathlib import Path
import hashlib
import html
import json
import subprocess

root = Path(__file__).resolve().parent
renderer = Path.home() / '.agents/skills/baoyu-post-to-wechat/scripts/md-to-wechat.ts'
bun = Path.home() / '.bun/bin/bun'
result = subprocess.run(
    [str(bun), '--no-install', '--no-env-file', str(renderer),
     str(root / '正文.md'), '--theme', 'grace', '--color', '#E06C75', '--no-cite'],
    check=True, capture_output=True, text=True,
)
rendered = json.loads(result.stdout)
content = Path(rendered['htmlPath']).read_text()
for item in rendered['contentImages']:
    relative = str(Path(item['localPath']).relative_to(root))
    image = (f'<img src="{html.escape(relative, quote=True)}" '
             f'alt="{html.escape(item.get("alt", ""), quote=True)}" '
             'style="display:block;width:100%;height:auto;margin:1.5em auto;">')
    content = content.replace(item['placeholder'], image)
viewport = '<meta name="viewport" content="width=device-width, initial-scale=1">'
if '<head>' in content:
    content = content.replace('<head>', '<head>' + viewport, 1)
else:
    content = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
               + viewport + '<title>' + html.escape(rendered['title'])
               + '</title></head><body>' + content + '</body></html>')
(root / '正文.html').write_text(content)
manifest = {
    'theme': 'grace', 'color': '#E06C75', 'citationMode': 'external-links-retained',
    'renderer': str(renderer),
    'rendererSha256': hashlib.sha256(renderer.read_bytes()).hexdigest(),
    'markdownSha256': hashlib.sha256((root / '正文.md').read_bytes()).hexdigest(),
    'htmlSha256': hashlib.sha256(content.encode()).hexdigest(),
    'images': [i['originalPath'] for i in rendered['contentImages']],
}
(root / '预览渲染.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'htmlPath': str(root / '正文.html'), **manifest}, ensure_ascii=False))
