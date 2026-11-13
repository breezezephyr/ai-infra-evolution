#!/usr/bin/env python3
"""P3·4 纸面算表：这张卡（RTX 4060 Laptop 8 GB，Qwen3-1.7B BF16）上的 PD 配比、KV 传输、排空时间。
全部用 P2 / P3 实测数，公式取自 ai-infra-book 9.2 / 9.6.1：
  μ_PD = min(μ_P, μ_D, B_net / V_KV)          T_drain = λ·T_s / (μ − λ)
用法：python3 pd_ratio.py            → 打印 markdown 表
      ../phase2/.venv/bin/python pd_ratio.py --plot → 另存 img/pd_ratio.png
"""
import math, sys, os

# ---- 实测输入（出处见注释）----
IN, OUT = 1024, 256            # exp1 负载
PREFILL_US = 300               # P2·下 两面对上：服务端 prefill 时间 ÷ 输入 token（预算 8192）
ITL_FULL_MS = 21.6             # P2·上 exp1 并发 16–32 的 ITL p50（车坐满，~10–12 人）
SEATS = 13_184                 # KV 座位（GPU_UTIL 0.90）
KV_PER_TOK = 28 * 8 * 128 * 2 * 2   # 层 × KV 头 × 头维 × (K,V) × BF16 = 114,688 B
MU_COLO = 372 / OUT            # exp1 并发 32 实测：372 tok/s ÷ 256 = 1.45 req/s（合车）
START_S = 43                   # exp6 窗口：bench-vllm 从 start 到 /health 就绪 43 s（18:05:48 → 18:06:31）

# ---- 一张卡当 P 车 / D 车各能扛多少 ----
d_P = IN * PREFILL_US / 1e6                      # 一条请求的 prefill 时间
mu_P = 1 / d_P                                   # P 车：一条接一条搬行李（上限，不算批内并行）
riders = SEATS // (IN + OUT)                     # D 车坐几人：座位 ÷ 每人行李
d_D = OUT * ITL_FULL_MS / 1e3                    # 一条请求在 D 车上跑多久
mu_D = riders / d_D                              # D 车：riders 人同时跑，每人 d_D 秒
V_KV = IN * KV_PER_TOK                           # P → D 要搬的 KV（只有输入那段）

def pd(nP, nD, bw_gbs):
    net = bw_gbs * 1e9 / V_KV
    return min(nP * mu_P, nD * mu_D, net), net

LINKS = [('PCIe Gen4 x16（同机，理论）', 32), ('RoCE 100G', 12.5), ('25GbE', 3.125), ('10GbE', 1.25)]

def tables():
    out = []
    out.append('## 一张卡当 P 车 / D 车\n')
    out.append('| | 算法 | 每张卡 req/s |\n|---|---|---|')
    out.append(f'| P 车（只搬行李） | 1 ÷ ({IN} × {PREFILL_US} µs = {d_P*1e3:.0f} ms) | **{mu_P:.2f}** |')
    out.append(f'| D 车（只跑圈） | {riders} 人 ÷ ({OUT} 圈 × {ITL_FULL_MS} ms = {d_D:.1f} s) | **{mu_D:.2f}** |')
    out.append(f'| 合车（实测 exp1 并发 32） | 372 tok/s ÷ {OUT} | **{MU_COLO:.2f}** |')
    r = mu_D / mu_P
    out.append(f'\n配比 P : D = μ_D : μ_P = 1 : {mu_P/mu_D:.2f}（每 {mu_P/mu_D:.2f} 张 D 车配 1 张 P 车）\n')
    out.append('## N 张卡怎么分\n')
    out.append('| 卡数 | 最优分法 | PD 吞吐 req/s | 合车 N × 1.45 | PD / 合车 |\n|---|---|---|---|---|')
    for n in (2, 3, 4, 8, 16):
        best = max(((p, n - p) for p in range(1, n)), key=lambda x: min(x[0] * mu_P, x[1] * mu_D))
        v = min(best[0] * mu_P, best[1] * mu_D)
        out.append(f'| {n} | {best[0]}P + {best[1]}D | {v:.2f} | {n*MU_COLO:.2f} | {v/(n*MU_COLO):.0%} |')
    out.append(f'\n## P → D 搬 KV：每条 {V_KV/1e6:.0f} MB（{IN} token × {KV_PER_TOK/1024:.0f} KB）；8K 上下文 {8192*KV_PER_TOK/1e9:.2f} GB\n')
    out.append(f'| 链路 | 1K 搬一次 | 占 prefill {d_P*1e3:.0f} ms 的 | 链路能扛 req/s | 8K 搬一次 |\n|---|---|---|---|---|')
    for name, bw in LINKS:
        t = V_KV / (bw * 1e9); t8 = 8192 * KV_PER_TOK / (bw * 1e9)
        out.append(f'| {name} | {t*1e3:.1f} ms | {t/d_P:.0%} | {bw*1e9/V_KV:.0f} | {t8*1e3:.0f} ms |')
    out.append(f'\n书 9.2：Qwen3-8B、8K 输入、1.125 GiB、25 GB/s → 48.3 ms。这张卡 1.7B、8K：{8192*KV_PER_TOK/1e9:.2f} GB、25 GB/s → {8192*KV_PER_TOK/25e9*1e3:.0f} ms。\n')
    out.append(f'## 排空：停 T_s = {START_S} s（一次重启），一张合车 μ = {MU_COLO:.2f} req/s\n')
    out.append('| 利用率 λ/μ | λ req/s | 攒下的人 λT_s | T_drain = λT_s/(μ−λ) | 从停到清空 |\n|---|---|---|---|---|')
    for u in (0.5, 0.7, 0.8, 0.9, 0.95):
        lam = u * MU_COLO; q = lam * START_S; td = q / (MU_COLO - lam)
        out.append(f'| {u:.0%} | {lam:.2f} | {q:.0f} | {td:.0f} s | {START_S+td:.0f} s（{(START_S+td)/60:.1f} min） |')
    return '\n'.join(out)

def plot():
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; from matplotlib import font_manager as fm
    for fp in ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc']:
        if os.path.exists(fp): fm.fontManager.addfont(fp); plt.rcParams['font.family'] = fm.FontProperties(fname=fp).get_name(); break
    BG, INK, MUTED, BLUE, ORANGE, GREEN = '#f8f5ee', '#1c1a17', '#6f695f', '#2f5f8a', '#c4763a', '#4f7a52'
    plt.rcParams.update({'axes.facecolor': '#ffffff', 'figure.facecolor': BG, 'axes.edgecolor': '#e6e0d4', 'text.color': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 13})
    fig, ax = plt.subplots(1, 2, figsize=(15, 5.4), dpi=160); fig.subplots_adjust(wspace=.25, left=.06, right=.98, top=.8, bottom=.14)
    fig.suptitle('P3·4 算表 · 拆车划不划算，停一次要多久', x=.06, ha='left', fontsize=15, fontweight='bold')
    fig.text(.06, .88, '进化之路 · P3·4 · Qwen3-1.7B · RTX 4060 8 GB · 输入 1024 / 输出 256 · 全部为实测数代入公式', color=MUTED, fontsize=11)
    ns = [2, 3, 4, 8, 16]; pdv = []
    for n in ns:
        pdv.append(max(min(p * mu_P, (n - p) * mu_D) for p in range(1, n)))
    x = range(len(ns)); w = .38
    ax[0].bar([i - w/2 for i in x], [n * MU_COLO for n in ns], w, color=BLUE, label='合车（实测 1.45 × N）')
    ax[0].bar([i + w/2 for i in x], pdv, w, color=ORANGE, label='拆车 PD（最优分法）')
    for i, (a, b) in enumerate(zip([n * MU_COLO for n in ns], pdv)):
        ax[0].text(i - w/2, a, f'{a:.1f}', ha='center', va='bottom', fontsize=10); ax[0].text(i + w/2, b, f'{b:.1f}', ha='center', va='bottom', fontsize=10)
    ax[0].set_xticks(list(x)); ax[0].set_xticklabels([f'{n} 张' for n in ns]); ax[0].set_title('吞吐 req/s：同构卡拆车不涨', loc='left', fontweight='bold'); ax[0].legend(frameon=False, fontsize=10); ax[0].grid(axis='y', color='#eee8dc')
    us = [i / 100 for i in range(30, 97)]
    ax[1].plot([u * 100 for u in us], [(START_S + u * MU_COLO * START_S / (MU_COLO - u * MU_COLO)) / 60 for u in us], color=GREEN, lw=2.5)
    for u in (0.5, 0.8, 0.9):
        v = (START_S + u * START_S / (1 - u)) / 60; ax[1].plot(u * 100, v, 'o', color=ORANGE); ax[1].text(u * 100 - 1, v + .4, f'{u:.0%} → {v:.1f} min', ha='right', fontsize=11)
    ax[1].set_title(f'停 {START_S} s 后多久清空（分钟）', loc='left', fontweight='bold'); ax[1].set_xlabel('利用率 λ/μ（%）'); ax[1].grid(axis='y', color='#eee8dc'); ax[1].set_ylim(0, 16)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img', 'pd_ratio.png'); fig.savefig(out); print(out)

print(tables())
if '--plot' in sys.argv: plot()
