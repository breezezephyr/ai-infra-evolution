#!/usr/bin/env python3
"""把一次 bench-vllm 启动的 journal 切成段。用法：startlog.py <name> <since 'YYYY-MM-DD HH:MM:SS.ffffff'> → 打印一行 JSON。"""
import json, re, subprocess, sys
from datetime import datetime
name, since = sys.argv[1], sys.argv[2]
out = subprocess.run(['journalctl', '-u', 'bench-vllm', '--no-pager', '-o', 'short-iso-precise', '--since', since], capture_output=True, text=True).stdout
MARK = [('start', r'Started bench-vllm'), ('api', r'vLLM API server version'), ('load0', r'Starting to load model'),
        ('load1', r'Model loading took'), ('compile', r'torch\.compile takes'), ('kv', r'GPU KV cache size'),
        ('graph', r'Graph capturing finished'), ('ready', r'Application startup complete')]
t = {}; extra = {}
for ln in out.splitlines():
    ts = ln.split(' ', 1)[0]
    for k, pat in MARK:
        if k not in t and re.search(pat, ln):
            t[k] = datetime.fromisoformat(ts).timestamp()
    m = re.search(r'Loading weights took ([\d.]+) seconds', ln); m and extra.setdefault('weights_s', float(m.group(1)))
    m = re.search(r'torch\.compile takes ([\d.]+) s', ln); m and extra.setdefault('compile_s', float(m.group(1)))
    m = re.search(r'Graph capturing finished in (\d+) secs', ln); m and extra.setdefault('graph_s_log', int(m.group(1)))
    if 'Directly load the compiled graph' in ln: extra['compile_cache'] = 'hit'
    if 'Compiling a graph for general shape' in ln: extra['compile_cache'] = 'miss'
    m = re.search(r'GPU KV cache size: ([\d,]+)', ln); m and extra.setdefault('kv_tokens', int(m.group(1).replace(',', '')))
seg = {}
def d(a, b):
    return round(t[b] - t[a], 2) if a in t and b in t else None
seg['进程+import'] = d('start', 'api')
seg['引擎进程+CUDA 初始化'] = d('api', 'load0')
seg['读权重'] = d('load0', 'load1')
seg['torch.compile'] = d('load1', 'compile')
seg['profile+KV'] = d('compile', 'kv') if 'compile' in t else d('load1', 'kv')
seg['CUDA graph'] = d('kv', 'graph')
seg['收尾'] = d('graph', 'ready') if 'graph' in t else d('kv', 'ready')
print(json.dumps({'name': name, 'total': d('start', 'ready'), 'seg': seg, **extra}, ensure_ascii=False))
