#!/usr/bin/env python3
"""exp9：扩容信号的提前量。用法：../phase2/.venv/bin/python plot_exp9.py（--no-plot 只打印表）
超标 t_breach：按到达时间滚动 10 s 的 TTFT 中位数首次 > 2 s。
信号：条件连续 5 s 成立的第一秒。提前量 = t_breach − t_signal；再对比出车时间（exp8：日常 44 s / 6 尺寸 27 s）。
"""
import json, glob, os, sys
H = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(H, 'results')
f = sorted(glob.glob(os.path.join(R, 'exp9-ramp-*.samp.jsonl')))[-1]
S = [json.loads(l) for l in open(f)]
QA = [json.loads(l) for l in open(f.replace('.samp.', '.req.'))]
Q = QA
Q = [q for q in Q if q['ttft_ms'] is not None]
MU = 1.45; SLO = 2000

def breach():
    for t in range(10, int(max(q['t_arr'] for q in Q))):
        w = sorted(q['ttft_ms'] for q in Q if t - 10 <= q['t_arr'] < t)
        if len(w) >= 3 and w[len(w) // 2] > SLO:
            return t
t_b = breach()

def first_hold(pred, hold=5):
    run = 0
    for s in S:
        run = run + 1 if pred(s) else 0
        if run >= hold:
            return s['t'] - hold + 1
    return None

def slope(i, win=15):
    xs = [S[j]['t'] for j in range(max(0, i - win + 1), i + 1)]; ys = [S[j].get('num_requests_waiting') or 0 for j in range(max(0, i - win + 1), i + 1)]
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
for i, s in enumerate(S):
    s['slope'] = slope(i)
    done = sorted(q['ttft_ms'] for q in Q if s['t'] - 20 <= q['t_arr'] + q['ttft_ms'] / 1e3 < s['t'])
    s['ttft_obs_p90'] = done[int(.9 * (len(done) - 1))] if done else 0
    s['lam_hat'] = sum(1 for q in QA if s['t'] - 30 <= q['t_arr'] < s['t']) / 30 if s['t'] >= 30 else 0

SIG = [('到达率 λ̂(30 s) ≥ 70% μ', lambda s: s['lam_hat'] >= .7 * MU),
       ('GPU 利用率 ≥ 90%', lambda s: (s.get('gpu_util') or 0) >= 90),
       ('KV 占用 ≥ 90%', lambda s: (s.get('gpu_cache_usage_perc') or 0) >= .9),
       ('running ≥ 10（座位满）', lambda s: (s.get('num_requests_running') or 0) >= 10),
       ('waiting 斜率 ≥ 0.1/s', lambda s: s['slope'] >= .1),
       ('waiting ≥ 5', lambda s: (s.get('num_requests_waiting') or 0) >= 5),
       ('已完成 TTFT p90 > 2 s', lambda s: s['ttft_obs_p90'] > SLO)]
lam = lambda t: next((s['lam'] for s in S if s['t'] >= t), None)
t_mu = next(s['t'] for s in S if s['lam'] >= MU)
rows = []
for name, p in SIG:
    t = first_hold(p)
    rows.append((name, t, lam(t) if t is not None else None, (t_b - t) if t is not None else None))
print(f'λ 越过 μ={MU}：t = {t_mu:.0f} s；首字超标（到达时间滚动 10 s 中位数 > 2 s）：t = {t_b} s\n')
print('| 信号 | 报警 t | 当时 λ | 提前量 | 够 27 s 出车？ | 够 44 s？ |\n|---|---|---|---|---|---|')
for n, t, l, lead in rows:
    ok = lambda x: '—' if lead is None else ('✓' if lead >= x else '✗')
    print(f"| {n} | {t if t is not None else '—'} | {l if l is not None else '—'} | {lead if lead is not None else '—'} s | {ok(27)} | {ok(44)} |")
json.dump({'t_mu': t_mu, 't_breach': t_b, 'signals': [dict(name=n, t=t, lam=l, lead=d) for n, t, l, d in rows]}, open(os.path.join(R, 'exp9-signals.json'), 'w'), ensure_ascii=False, indent=1)
if '--no-plot' in sys.argv:
    sys.exit()
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
for fp in ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family'] = fm.FontProperties(fname=fp).get_name(); break
BG, INK, MUTED, BLUE, ORANGE, GREEN, RED = '#f8f5ee', '#1c1a17', '#6f695f', '#2f5f8a', '#c4763a', '#4f7a52', '#a84d3a'
plt.rcParams.update({'axes.facecolor': '#ffffff', 'figure.facecolor': BG, 'axes.edgecolor': '#e6e0d4', 'text.color': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 12})
fig, ax = plt.subplots(3, 1, figsize=(14, 9), dpi=160, sharex=True); fig.subplots_adjust(hspace=.12, left=.07, right=.97, top=.88, bottom=.07)
fig.suptitle('exp9 · 爬坡负载下，哪个信号先响', x=.07, ha='left', fontsize=15, fontweight='bold')
fig.text(.07, .915, f'进化之路 · P3b·1 · Qwen3-1.7B · λ {S[0]["lam"]:.1f} → 2.2 req/s 爬 240 s + 保持 60 s · 合车 μ ≈ {MU}', color=MUTED, fontsize=11)
T = [s['t'] for s in S]
a = ax[0]; a.scatter([q['t_arr'] for q in Q], [q['ttft_ms'] / 1e3 for q in Q], s=8, color=BLUE, alpha=.6, label='每条请求 TTFT（按到达）')
a.axhline(SLO / 1e3, color=RED, lw=1, ls='--'); a.set_ylabel('TTFT s'); a2 = a.twinx(); a2.plot(T, [s['lam'] for s in S], color=MUTED, lw=1.5, label='λ 设定'); a2.plot(T, [s['lam_hat'] for s in S], color=ORANGE, lw=1, alpha=.8, label='λ̂ 最近 30 s 实测'); a2.legend(frameon=False, fontsize=10, loc='upper center'); a2.axhline(MU, color=MUTED, lw=.8, ls=':'); a2.set_ylabel('λ req/s', color=MUTED); a2.spines['top'].set_visible(False)
a.legend(frameon=False, fontsize=10, loc='upper left')
b = ax[1]; b.plot(T, [s.get('num_requests_waiting') or 0 for s in S], color=ORANGE, lw=2, label='waiting'); b.plot(T, [s.get('num_requests_running') or 0 for s in S], color=GREEN, lw=2, label='running'); b.set_ylabel('条'); b.legend(frameon=False, fontsize=10, loc='upper left')
c = ax[2]; c.plot(T, [s.get('gpu_util') or 0 for s in S], color=BLUE, lw=1.5, label='GPU 利用率 %'); c.plot(T, [100 * (s.get('gpu_cache_usage_perc') or 0) for s in S], color=GREEN, lw=1.5, label='KV 占用 %'); c.set_ylabel('%'); c.set_xlabel('秒'); c.legend(frameon=False, fontsize=10, loc='lower right')
for axx in ax:
    axx.axvline(t_b, color=RED, lw=1.5); axx.axvline(t_mu, color=MUTED, lw=1, ls=':')
    for n, t, l, d in rows:
        if t is not None: axx.axvline(t, color='#c9bfae', lw=.8)
ax[0].text(t_b + 2, ax[0].get_ylim()[1] * .9, '首字超标', color=RED, fontsize=11)
ax[0].text(t_mu + 2, ax[0].get_ylim()[1] * .75, 'λ = μ', color=MUTED, fontsize=11)
t_l = rows[0][1]
if t_l: ax[0].text(t_l - 2, ax[0].get_ylim()[1] * .6, f'λ̂ ≥ 70% μ\n提前 {t_b - t_l:.0f} s', color=ORANGE, fontsize=11, ha='right')
out = os.path.join(H, 'img', 'exp9.png'); fig.savefig(out); print(out)
