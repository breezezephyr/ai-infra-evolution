#!/usr/bin/env python3
"""exp10：排空。每个期限一组：排空开始时在途几条、期限内跑完几条（最晚一条多久）、被断几条、被断的人已出了多少字。"""
import json, glob, os
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
print('| 期限 | 排空时在途 | 期限内跑完 | 最晚一条（排空后） | 被断 | 被断者已出字 / 要出的 | 白跑的字 | 排空期间拒绝 |\n|---|---|---|---|---|---|---|---|')
out = {}
for dl in (0, 5, 10, 30):
    fs = sorted(glob.glob(os.path.join(R, f'exp10-dl{dl}-*.gw.jsonl')))
    if not fs:
        continue
    g = [json.loads(l) for l in open(fs[-1])]
    st = next(r for r in g if r.get('outcome') == 'drain_start')
    ok = [r for r in g if r.get('outcome') == 'ok' and r.get('after_drain_ms') is not None]
    cut = [r for r in g if r.get('outcome') == 'drain_cut']
    rej = sum(1 for r in g if r.get('outcome') == 'drain_reject')
    lost = sum(r['chunks'] for r in cut)
    frac = ', '.join(f"{r['chunks']}/{r['max_tokens']}" for r in sorted(cut, key=lambda r: r['max_tokens']))
    out[dl] = dict(inflight=st['inflight'], finished=len(ok), last_ms=max((r['after_drain_ms'] for r in ok), default=0), cut=len(cut), lost_tokens=lost, rejected=rej, cut_detail=[(r['chunks'], r['max_tokens']) for r in cut])
    print(f"| {dl} s | {st['inflight']} | {len(ok)} | {max((r['after_drain_ms'] for r in ok), default=0) / 1e3:.1f} s | {len(cut)} | {frac or '—'} | {lost} | {rej} |")
json.dump(out, open(os.path.join(R, 'exp10-summary.json'), 'w'), indent=1)
