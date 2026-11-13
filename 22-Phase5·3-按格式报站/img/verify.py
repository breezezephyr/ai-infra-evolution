"""Verify this graphic set; optional rerender proves same-environment determinism.

Run with -B. All output is restricted to this directory. No model or tool calls.
"""
import sys
sys.dont_write_bytecode = True
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import struct
import subprocess

D = Path(__file__).resolve().parent
SOURCE = D.parent.parent / '21-Phase5·2-广播分几段' / 'img'
NAMES = {'00-封面': (2560, 1090), '01-一页纸': (2160, 4160)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_hashes():
    return {f'{name}.{ext}': digest(D / f'{name}.{ext}')
            for name in NAMES for ext in ('html', 'png', 'layout.json')}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text_of(html):
    parser = VisibleText()
    parser.feed(html)
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()


def verify(rerender=False):
    before = artifact_hashes()
    if rerender:
        assert os.environ.get('SERIES_PREVIEW_URL', '').startswith('http://127.0.0.1:'), \
            'Rerender requires the local HTTP preview URL'

        def run(script):
            result = subprocess.run([sys.executable, '-B', str(D / script)],
                                    capture_output=True, text=True, timeout=70)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout.strip()

        with ThreadPoolExecutor(max_workers=2) as pool:
            for output in pool.map(run, ['cover.py', 'build.py']):
                print(output)
        after = artifact_hashes()
        assert before == after, 'Repeated render changed HTML, PNG, or DOM evidence'
        determinism = {'checked': True, 'method': 'Repeated Chrome render over local HTTP',
                       'scope': 'Same machine, browser and installed fonts',
                       'first_sha256': before, 'second_sha256': after, 'identical': True}
    else:
        determinism = {'checked': False}

    baseline = json.loads((D / 'source-hashes.json').read_text())['sha256_before']
    source_now = {p.name: digest(p) for p in sorted(SOURCE.iterdir()) if p.is_file()}
    assert baseline == source_now, 'Previous article img files changed'

    layouts = {}
    for name, expected in NAMES.items():
        report = json.loads((D / f'{name}.layout.json').read_text())
        assert not report['issues'] and not report['sibling_overlap_issues']
        assert not report['runtime_errors'] and report['font_status'] == 'loaded'
        assert report['dpr'] == 2 and report['checked_sibling_pairs'] > 0
        header = (D / f'{name}.png').read_bytes()[:24]
        assert header[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', header[16:24]) == expected
        assert (report['png_width'], report['png_height']) == expected
        layouts[name] = {'png_size': expected, 'overflow_issues': report['issues'],
                         'sibling_overlap_issues': report['sibling_overlap_issues'],
                         'runtime_errors': report['runtime_errors'],
                         'checked_elements': report['checked_elements'],
                         'checked_text_lines': report['checked_text_lines'],
                         'checked_sibling_pairs': report['checked_sibling_pairs']}

    cover = json.loads((D / '00-封面.layout.json').read_text())
    stations = cover['cover_stations']
    assert [s['phase'] for s in stations] == ['0', '1', '2', '3', '3b', '4', '5']
    assert [s['phase'] for s in stations if s['opacity'] == 1] == ['5']
    assert all(s['opacity'] == .28 for s in stations if s['phase'] != '5')
    assert stations[-1]['fill'].upper() == '#F2D479'
    cover_html = (D / '00-封面.html').read_text()
    assert '进化之路 · P5 · 3' in cover_html
    assert '<div class="big">按格式报站</div>' in cover_html
    assert '<div class="title">结构化输出谁来保证</div>' in cover_html

    html = (D / '01-一页纸.html').read_text()
    visible = text_of(html)
    required = [
        '声明 JSON / schema，就认为输出可靠。',
        '请求接受 ≠ 执行约束', 'JSON 可解析 ≠ schema 合格',
        'schema 合格 ≠ 业务答案正确', '工具约束不能直接 当 JSON 约束透传。',
        '固定任务与 seed', '固定原生 Qwen 模板', '保存 API 入口实际设置',
        '保存实际响应', '拒绝 / 失败 / 未知仍计入分母',
        '格式受约束，答案仍要核对。',
        'CPU 真实 recipe 转换＋小 GPU 后端独立对照。',
        '独立验证 recipe 转换与 parser，不接 GPU。',
        '核对语义对应字段，不串接两线产物。',
        'vLLM 0.8.5 · Qwen3-0.6B 已实际生成。',
        'recipe prompt / OutputConstraint 未直接接入 Qwen。',
        '两线未端到端集成；未运行 DeepInfer。',
        '数组 maxItems → 400；不静默削弱 schema。',
        '工具只作声明： 记录约束，不执行工具。',
    ]
    assert all(phrase in visible for phrase in required), [p for p in required if p not in visible]
    layers = [text_of(s) for s in re.findall(r'<div class="step">.*?<h3>(.*?)</h3>', html, re.S)]
    assert layers == ['声明', 'CPU 线：真实 recipe 转换', '两线核对：显式语义映射 / 拒绝',
                      'GPU 线：后端独立采样生成', '独立 JSON / schema / 业务校验']
    assert not any('↓' in layer or '→' in layer for layer in layers)
    forbidden = ['待补', 'TODO', 'TBD', '通过率', '实测结果', '条件满足时', '条件性小 GPU']
    assert not any(word in visible for word in forbidden)
    assert not re.search(r'\d+(?:\.\d+)?\s*(?:%|条|次|项|秒|样本|请求)', visible)
    assert not re.search(r'<(?:script[^>]+src|link[^>]+href|img\s)', html, re.I)

    report = {
        'status': 'PASS', 'write_scope': str(D),
        'layout': layouts, 'cover_stations': stations,
        'required_content': required, 'five_layers': layers,
        'experimental_result_numbers_embedded': False,
        'gpu_status_claim_embedded': True,
        'experiment_fact_source': 'User update in current conversation; no model experiment executed by the graphics scripts',
        'experiment_boundary': {
            'cpu': 'Real recipe conversion and parser probes',
            'gpu': 'Independent native-Qwen-template generation on DARYU 4060 / vLLM 0.8.5 / Qwen3-0.6B',
            'relationship': 'Explicit semantic-field mapping only; no end-to-end integration',
            'recipe_prompt_or_OutputConstraint_connected_to_Qwen': False,
            'DeepInfer_executed': False,
            'array_maxItems': 'HTTP 400 rejected in this version; no silent schema weakening',
            'refusals_failures_unknowns_in_denominator': True,
        },
        'tools': 'Declarations only; no execution',
        'previous_article': {'directory': str(SOURCE), 'all_files_unchanged': True,
                             'verified_files': len(baseline), 'sha256_after': source_now},
        'determinism': determinism,
        'artifact_sha256': artifact_hashes(),
    }
    (D / '图卡检查.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: dimensions / overflow / sibling intersections / runtime / content / station 5 / source preservation')
    if rerender:
        print('PASS: repeat-render SHA256 identical for both HTML, PNG and layout reports')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rerender', action='store_true')
    verify(parser.parse_args().rerender)
