"""Render the series HTML at 2x and reject clipped or overflowing text."""
import json
import os
from urllib.parse import quote
import pathlib
import re
import struct
import subprocess
import tempfile

D = pathlib.Path(__file__).resolve().parent
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

CHECK = r'''
<script>
addEventListener('load', async () => {
  await document.fonts.ready;
  const W = __WIDTH__, H = __HEIGHT__, issues = [];
  for (const el of document.querySelectorAll('body, body *')) {
    if (!(el instanceof HTMLElement) || /^(SCRIPT|STYLE)$/.test(el.tagName)) continue;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.display === 'none') continue;
    if (cs.display !== 'inline' && el.clientWidth && el.scrollWidth > el.clientWidth + 2)
      issues.push(`${el.tagName}.${el.className}: horizontal overflow`);
    if (cs.display !== 'inline' && el.clientHeight && el.scrollHeight > el.clientHeight + 2)
      issues.push(`${el.tagName}.${el.className}: vertical overflow ${el.scrollHeight}/${el.clientHeight}, line-height ${cs.lineHeight}`);
    if (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1)
      issues.push(`${el.tagName}.${el.className}: outside canvas`);
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (!n.textContent.trim() || /^(SCRIPT|STYLE)$/.test(n.parentElement.tagName)) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1)
        issues.push(`text outside canvas: ${n.textContent.trim().slice(0, 32)}`);
    }
  }
  const report = document.createElement('script');
  report.id = 'layout-check'; report.type = 'application/json';
  const selectors = ['.kick','.big','.title','.eyebrow','h1','.sub','.info h2',
    '.info p','.failure strong','.failure p','.step h3','.step p',
    '.check strong','.check p','.states h3','.state','.boundary>strong','.limits p','.footer'];
  const typography = {};
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (!el) continue;
    const cs = getComputedStyle(el);
    typography[selector] = {font_size_css_px: parseFloat(cs.fontSize),
      font_size_png_px: parseFloat(cs.fontSize) * devicePixelRatio,
      line_height_css_px: parseFloat(cs.lineHeight), font_family: cs.fontFamily,
      color: cs.color};
  }
  const blockBounds = [...document.querySelectorAll('body>.eyebrow,body>h1,body>.sub,.info,.boundary,.footer,.card')]
    .map(el => { const r = el.getBoundingClientRect(); return {selector:el.className || el.tagName,
      top:r.top, bottom:r.bottom, left:r.left, right:r.right}; });
  const siblingOverlapIssues = [];
  for (const parent of [document.body, ...document.querySelectorAll('.four,.flow,.states')]) {
    const blocks = [...parent.children].filter(el => {
      if (!(el instanceof HTMLElement) || /^(SCRIPT|STYLE|CANVAS)$/.test(el.tagName)) return false;
      const cs = getComputedStyle(el); return cs.position !== 'absolute' && cs.display !== 'none';
    });
    for (let i=1;i<blocks.length;i++) {
      const previous=blocks[i-1].getBoundingClientRect(), current=blocks[i].getBoundingClientRect();
      if (current.top < previous.bottom - 1) siblingOverlapIssues.push(blocks[i].className || blocks[i].tagName);
    }
  }
  issues.push(...siblingOverlapIssues.map(x => `overlapping sibling: ${x}`));
  const coverStations = [...document.querySelectorAll('svg>g')].map(el => ({
    phase:el.querySelector('text')?.textContent,opacity:parseFloat(el.getAttribute('opacity')),
    radius:parseFloat(el.querySelector('circle')?.getAttribute('r'))}));
  report.textContent = JSON.stringify({width: W, height: H, dpr: devicePixelRatio, issues,
    page_title:document.title,font_status:document.fonts.status,
    typography,block_bounds:blockBounds,cover_stations:coverStations,
    sibling_overlap_issues:siblingOverlapIssues});
  document.body.append(report);
});
</script>
'''


def render(name, html, width, height):
    html_path = D / f'{name}.html'
    png_path = D / f'{name}.png'
    check = CHECK.replace('__WIDTH__', str(width)).replace('__HEIGHT__', str(height))
    html_path.write_text(html.replace('</body>', check + '</body>'), encoding='utf-8')
    preview_url = os.environ.get('SERIES_PREVIEW_URL')
    target = preview_url.rstrip('/') + '/' + quote(html_path.name) if preview_url else html_path.as_uri()
    with tempfile.TemporaryDirectory(prefix='.chrome-', dir=D) as profile:
        result = subprocess.run([
            CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
            '--no-first-run', '--no-default-browser-check',
            f'--user-data-dir={profile}', '--force-device-scale-factor=2',
            f'--window-size={width},{height}', '--virtual-time-budget=1200',
            '--dump-dom', f'--screenshot={png_path}', target,
        ], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    match = re.search(r'<script id="layout-check" type="application/json">(.*?)</script>',
                      result.stdout, re.S)
    if not match:
        raise RuntimeError('No browser layout report: ' + result.stderr[-1000:])
    report = json.loads(match.group(1))
    with png_path.open('rb') as image:
        header = image.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('Invalid PNG')
    actual = struct.unpack('>II', header[16:24])
    if actual != (width * 2, height * 2):
        raise RuntimeError(f'PNG size mismatch: {actual}')
    if report['dpr'] != 2 or report['issues']:
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    (D / f'{name}.layout.json').write_text(json.dumps({**report, 'png_width': actual[0], 'png_height': actual[1]}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{name}.png: {actual[0]}x{actual[1]} / CSS {width}x{height} @2x / overflow=0')

