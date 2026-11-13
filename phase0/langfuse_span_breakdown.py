#!/usr/bin/env python3
"""Phase 0 · 从 Langfuse generation span 反推服务端剖面。

拆解： 端到端 = 网络地板 + 排队 + prefill + decode
  TTFT   = completionStartTime - startTime
  decode = endTime - completionStartTime
  TPOT   = decode / (output_tokens - 1)
可选：metadata.chunk_times = [ms 相对 startTime ...] 时，额外算 chunk 间隔分布与「周期性顿」。

适配 Langfuse v4（/v2/observations, cursor）与 v3（/observations, page）：按 /health 版本自动选。v4：GET /api/public/v2/observations?fields=core,usage,model,metadata&type=GENERATION，cursor 分页；
列表直接给 timeToFirstToken(s) / latency(s) / usageDetails / model / metadata。v3 的 /observations 已 410。

用法：
  LANGFUSE_HOST=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... \
  python3 langfuse_span_breakdown.py --limit 200 [--model xxx] [--name xxx] [--from 2026-09-01] [--csv out.csv]
  或 --env ~/.keep/.calorie.env --prefix KEEP_LANGFUSE_   （读 KEEP_LANGFUSE_HOST / _PUBLIC_KEY / _SECRET_KEY）
"""
import argparse, base64, json, os, sys, statistics as st, urllib.parse, urllib.request
from datetime import datetime, timezone

def load_env(path, prefix):
    env = {}
    for line in open(os.path.expanduser(path)):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1); env[k.strip()] = v.strip().strip('"').strip("'")
    return {'host': env.get(prefix+'HOST'), 'pk': env.get(prefix+'PUBLIC_KEY'), 'sk': env.get(prefix+'SECRET_KEY')}

def api(cfg, path, params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = cfg['host'].rstrip('/') + path + ('?' + q if q else '')
    auth = base64.b64encode(f"{cfg['pk']}:{cfg['sk']}".encode()).decode()
    req = urllib.request.Request(url, headers={'Authorization': 'Basic ' + auth})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)

def ts(s):
    if not s: return None
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def fetch(cfg, limit, model, name, since, fields='core,basic,usage,model,metadata'):
    """v4: /v2/observations + cursor；v3: /observations + page。按 health 版本号选。"""
    try: ver = api(cfg, '/api/public/health', {}).get('version', '')
    except Exception: ver = ''
    v4 = not ver.startswith('3.')
    out, cursor, page = [], None, 1
    while len(out) < limit:
        if v4:
            r = api(cfg, '/api/public/v2/observations', {'type': 'GENERATION', 'limit': min(100, limit-len(out)), 'cursor': cursor,
                                                           'model': model, 'name': name, 'fromStartTime': since, 'fields': fields})
        else:
            r = api(cfg, '/api/public/observations', {'type': 'GENERATION', 'limit': min(100, limit-len(out)), 'page': page,
                                                        'model': model, 'name': name, 'fromStartTime': since})
        data = r.get('data', [])
        if not data: break
        out += data
        if v4:
            cursor = (r.get('meta') or {}).get('cursor')
            if not cursor: break
        else:
            page += 1
            if page > (r.get('meta') or {}).get('totalPages', 1): break
    return out[:limit]

def breakdown(o):
    t0, t1 = ts(o.get('startTime')), ts(o.get('endTime'))
    ud = o.get('usageDetails') or {}
    g = lambda *ks: sum(int(ud.get(k) or 0) for k in ks)
    inp = ud.get('input') or g('input_text_tokens','input_audio_tokens') or o.get('inputUsage') or 0
    outp = ud.get('output') or g('output_text_tokens','output_audio_tokens') or o.get('outputUsage') or 0
    cached = (ud.get('input_cached_tokens') or ud.get('cached_tokens') or ud.get('cache_read_input_tokens') or ud.get('input_cache_read')
              or g('cached_text_tokens','cached_audio_tokens') or None)
    # 豆包 realtime 的 input_text_tokens 是「未命中部分」，命中部分单独记在 cached_*：总输入 = 未命中 + 命中
    if cached and 'input_text_tokens' in ud and 'input' not in ud: inp = inp + cached
    md = o.get('metadata') or {}
    if isinstance(md, str):
        try: md = json.loads(md)
        except ValueError: md = {}
    row = {'id': o.get('id'), 'trace': o.get('traceId'), 'name': o.get('name'), 'model': o.get('model') or o.get('modelId'),
           'start': t0, 'in': inp, 'out': outp, 'e2e_ms': None, 'ttft_ms': None, 'decode_ms': None, 'tpot_ms': None, 'tps': None,
           'cached': cached, 'chunks': None}
    if t0 and t1: row['e2e_ms'] = (t1-t0).total_seconds()*1000
    tf = ts(o.get('completionStartTime'))
    ttft = (tf-t0).total_seconds() if (tf and t0) else o.get('timeToFirstToken')
    if isinstance(ttft, (int, float)) and ttft > 100: ttft = ttft/1000  # v3 的 timeToFirstToken 是 ms
    if ttft is None and isinstance(md, dict):
        for k in ('ttft_ms', 'ttftMs', 'first_token_ms', 'firstTokenMs'):
            if k in md: ttft = float(md[k])/1000; break
    if ttft is not None and row['e2e_ms'] is not None:
        row['ttft_ms'] = ttft*1000
        row['decode_ms'] = row['e2e_ms'] - row['ttft_ms']
        if outp and outp > 1 and row['decode_ms'] > 0:
            row['tpot_ms'] = row['decode_ms']/(outp-1); row['tps'] = 1000/row['tpot_ms']
    ct = md.get('chunk_times') if isinstance(md, dict) else None
    if isinstance(ct, list) and len(ct) > 2:
        gaps = [b-a for a, b in zip(ct, ct[1:])]
        med = st.median(gaps) or 1
        row['chunks'] = {'n': len(ct), 'gap_p50': med, 'gap_p95': sorted(gaps)[max(0,int(len(gaps)*.95)-1)], 'gap_max': max(gaps),
                         'stalls': sum(1 for g in gaps if g > 3*med)}
    return row

def fit3(rows):
    """e2e ≈ a + b·input + c·output —— 没有 TTFT 时，用同一模型多条 span 把地板 / prefill / TPOT 一起解出来。"""
    X=[(1.0,float(r['in']),float(r['out'])) for r in rows]; y=[float(r['e2e_ms']) for r in rows]; n=len(X)
    if n < 30: return None
    A=[[sum(x[i]*x[j] for x in X) for j in range(3)] for i in range(3)]; b=[sum(x[i]*yy for x,yy in zip(X,y)) for i in range(3)]
    for i in range(3):
        p=A[i][i]
        if abs(p) < 1e-12: return None
        A[i]=[v/p for v in A[i]]; b[i]/=p
        for k in range(3):
            if k!=i:
                f=A[k][i]; A[k]=[vk-f*vi for vk,vi in zip(A[k],A[i])]; b[k]-=f*b[i]
    a,bi,bo=b; my=sum(y)/n
    ss_tot=sum((yy-my)**2 for yy in y); ss_res=sum((yy-(a+bi*x[1]+bo*x[2]))**2 for x,yy in zip(X,y))
    return a,bi,bo,(1-ss_res/ss_tot) if ss_tot else 0

def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs)-1, int(len(xs)*p))] if xs else None

def linfit(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = sum(xs)/n, sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs); sxy = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    if sxx == 0: return None
    b = sxy/sxx; a = my-b*mx
    ss_tot = sum((y-my)**2 for y in ys); ss_res = sum((y-(a+b*x))**2 for x, y in zip(xs, ys))
    return a, b, (1-ss_res/ss_tot) if ss_tot else 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env'); ap.add_argument('--prefix', default='LANGFUSE_')
    ap.add_argument('--limit', type=int, default=200); ap.add_argument('--model'); ap.add_argument('--name')
    ap.add_argument('--from', dest='since'); ap.add_argument('--csv'); ap.add_argument('--json')
    a = ap.parse_args()
    cfg = load_env(a.env, a.prefix) if a.env else {'host': os.environ.get('LANGFUSE_HOST'), 'pk': os.environ.get('LANGFUSE_PUBLIC_KEY'), 'sk': os.environ.get('LANGFUSE_SECRET_KEY')}
    if not all(cfg.values()): sys.exit('缺少 host / public key / secret key')
    obs = fetch(cfg, a.limit, a.model, a.name, a.since)
    rows = [breakdown(o) for o in obs]
    ok = [r for r in rows if r['ttft_ms'] is not None]
    print(f"拉取 {len(rows)} 条 generation，其中 {len(ok)} 条有 timeToFirstToken（TTFT 可算）。")
    if len(ok) < len(rows):
        print(f"  {len(rows)-len(ok)} 条缺首 token 时刻：流式回调里调用 generation.update(completion_start_time=now)（或 metadata.ttft_ms）即可补上。")
    # 端到端总览（所有条目都能算）
    byn = {}
    for r in rows: byn.setdefault(r['name'] or '?', []).append(r)
    print("\n== 端到端耗时（按 span 名）")
    for n, rs in sorted(byn.items(), key=lambda kv: -len(kv[1])):
        e = [r['e2e_ms'] for r in rs if r['e2e_ms'] is not None]
        ins = [r['in'] for r in rs if r['in']]; outs=[r['out'] for r in rs if r['out']]
        mods = sorted({str(r['model']) for r in rs if r['model']})
        if e: print(f"  {n:45s} n={len(rs):3d}  e2e p50 {pct(e,.5):6.0f} ms  p95 {pct(e,.95):6.0f} ms  min {min(e):5.0f}"
                    + (f"  in p50 {pct(ins,.5):.0f} out p50 {pct(outs,.5):.0f}" if ins and outs else "  (无 usage)")
                    + (f"  model {','.join(mods)[:40]}" if mods else ""))
        ch = [r for r in rs if r['cached']]
        if ch:
            ratio = [r['cached']/r['in'] for r in ch if r['in']]
            print(f"    prefix cache：{len(ch)}/{len(rs)} 条命中，命中 token p50 {pct([r['cached'] for r in ch],.5):.0f}，占输入 p50 {pct(ratio,.5)*100:.0f}%  ← 03 篇「只缓存完整 block」：命中量应是 block 的整数倍")
        fit = linfit([r['in'] for r in rs if r['in'] and r['e2e_ms']], [r['e2e_ms'] for r in rs if r['in'] and r['e2e_ms']])
        if fit and len(ins) >= 5:
            a0, b, r2 = fit; print(f"    e2e ~ {a0:.0f} ms + {b*1000:.1f} µs × input_tokens (R²={r2:.2f})")

    # 按模型分组
    by = {}
    for r in ok: by.setdefault(r['model'] or '?', []).append(r)
    for m, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        ttft = [r['ttft_ms'] for r in rs]; tpot = [r['tpot_ms'] for r in rs if r['tpot_ms']]; tps = [r['tps'] for r in rs if r['tps']]
        print(f"\n== {m}  n={len(rs)}")
        print(f"  TTFT  p50 {pct(ttft,.5):7.0f} ms   p95 {pct(ttft,.95):7.0f} ms   min {min(ttft):6.0f} ms  ← min 近似「网络 + 网关 + 最短 prefill」地板")
        if tpot: print(f"  TPOT  p50 {pct(tpot,.5):7.1f} ms   p95 {pct(tpot,.95):7.1f} ms   → 输出 {pct(tps,.5):5.1f} tok/s (p50)")
        fit = linfit([r['in'] for r in rs], [r['ttft_ms'] for r in rs])
        if fit:
            a0, b, r2 = fit
            print(f"  TTFT ~ {a0:.0f} ms + {b*1000:.1f} µs × input_tokens   (R²={r2:.2f})  → 截距≈地板+排队，斜率≈prefill 每 token 成本")
            if r2 < .3: print("    R² 偏低：输入长度解释不了 TTFT，说明排队 / batch 邻居的影响大于 prefill，本身就是一个发现。")
        cached = [r for r in rs if r['cached']]
        if cached: print(f"  prefix cache：{len(cached)} 条有 cached_tokens，命中量 p50 {pct([r['cached'] for r in cached],.5)}")
        # 按小时
        hours = {}
        for r in rs: hours.setdefault(r['start'].astimezone().hour, []).append(r['ttft_ms'])
        if len(hours) >= 3:
            line = '  按小时 TTFT p50：' + '  '.join(f"{h:02d}h {pct(v,.5):.0f}" for h, v in sorted(hours.items()))
            print(line + '   ← 输入不变时的小时差 = 排队 + batch 变化')
        ch = [r['chunks'] for r in rs if r['chunks']]
        if ch:
            print(f"  chunk 间隔：p50 {st.median(c['gap_p50'] for c in ch):.0f} ms，max {max(c['gap_max'] for c in ch):.0f} ms，"
                  f"顿(>3×中位) 平均 {st.mean(c['stalls'] for c in ch):.1f} 次/请求 ← 周期性顿 = 同 batch 有人 prefill")
        else:
            print("  无 chunk_times：把每个流式 chunk 到达的 ms 偏移写进 metadata.chunk_times，就能看到 batch 邻居。")

    # 没 TTFT 时的替代拆解：同一模型跨 span 三参数拟合
    bym = {}
    for r in rows:
        if r['model'] and r['e2e_ms'] and r['in'] and r['out']: bym.setdefault(str(r['model']), []).append(r)
    printed = False
    for m, rs in sorted(bym.items(), key=lambda kv: -len(kv[1])):
        f = fit3(rs)
        if not f: continue
        if not printed: print("\n== 无 TTFT 的替代拆解：e2e ≈ 地板 + prefill×input + TPOT×output（同一模型跨 span 拟合）"); printed = True
        a0, bi, bo, r2 = f
        flag = "" if r2 >= .6 else "  ← R² 低，排队/隐藏 reasoning 主导，别信系数"
        print(f"  {m[:40]:40s} n={len(rs):3d}  地板 {a0:5.0f} ms  prefill {bi*1000:5.1f} µs/tok  TPOT {bo:5.2f} ms/tok (≈{(1000/bo if bo>0 else 0):4.0f} tok/s)  R²={r2:.2f}{flag}")

    if a.csv:
        import csv
        with open(a.csv, 'w', newline='') as f:
            w = csv.writer(f); w.writerow(['id','trace','name','model','start','in','out','cached','e2e_ms','ttft_ms','decode_ms','tpot_ms','tps'])
            for r in rows: w.writerow([r[k] if k!='start' else (r['start'].isoformat() if r['start'] else '') for k in ['id','trace','name','model','start','in','out','cached','e2e_ms','ttft_ms','decode_ms','tpot_ms','tps']])
        print(f"\n明细已写入 {a.csv}")
    if a.json:
        json.dump([{**r, 'start': r['start'].isoformat() if r['start'] else None} for r in rows], open(a.json,'w'), ensure_ascii=False, indent=1)

if __name__ == '__main__': main()
