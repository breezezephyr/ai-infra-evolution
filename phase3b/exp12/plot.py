#!/usr/bin/env python3
"""../phase2/.venv/bin/python exp12/plot.py，从仓库根运行也可。"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[2]
d = json.loads((ROOT / 'phase3b/results/exp12-summary.json').read_text())
plt.rcParams['font.family'] = ['PingFang SC', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False
fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.8), facecolor='#f8f5ee')
colors = ['#2f5f8a', '#4f7a52', '#88709a', '#c4763a']
a = axes[0]
names = ['轮询', '前缀哈希', '哈希 Zipf', '有界哈希']
y = [r['points_per_1000_completions'] for r in d['runs']]
a.bar(names, y, color=colors, width=.65)
for i, value in enumerate(y):
    a.text(i, value + 15, f'{value:.0f}', ha='center', fontsize=10)
a.set_ylim(0, 1130); a.set_title('示例 token 账：每千次完成', pad=14)
a.set_ylabel('点数（费率 1 / 0.2 / 3 每千 token）')
a.text(.5, -.25, '按默认 16-token 块折算 × 示例费率', transform=a.transAxes,
       ha='center', fontsize=9, color='#6f695f')
a = axes[1]
r = d['runs'][1]
v = [r['decode_interval_sum_s'], r['decode_overlap_allocated_s']]
a.bar(['逐流直接相加', '共享时段分摊'], v, color=['#c4763a', '#4f7a52'], width=.6)
for i, value in enumerate(v):
    a.text(i, value + 20, f'{value:.1f} s', ha='center', fontsize=11)
a.axhline(r['observed_window_s'], ls='--', lw=1, color='#2f5f8a')
a.text(.96, .21, f"观测窗 {r['observed_window_s']:.1f}s", ha='right', transform=a.transAxes,
       color='#2f5f8a', fontsize=10)
a.set_ylim(0, 1350); a.set_title('一张卡，生成流时段会重叠', pad=14)
a.set_ylabel('秒')
a.text(.5, -.25, '哈希组；分摊为代理，未追踪 GPU 核函数', transform=a.transAxes,
       ha='center', fontsize=9, color='#6f695f')
a = axes[2]
q = d['queue']['rows_detail']
ok = [r for r in q if r['wait_s'] is not None and r['wait_s'] > .001]
a.scatter([r['wait_s'] for r in ok], [r['prediction_s'] for r in ok],
          alpha=.6, s=14, color='#2f5f8a', label='133 条等到准入的请求')
a.plot([0, 11], [0, 11], '--', color='#4f7a52', lw=1, label='预测 = 实际')
a.set_xlabel('实际网关等待 / s'); a.set_ylabel('按排位 / 历史服务率预测 / s')
a.set_xlim(0, 11); a.set_ylim(0, 25); a.set_title('叫号预估：±30% 只覆盖 19.5%', pad=14)
a.legend(frameon=False, fontsize=8, loc='upper left')
a.text(.5, -.25, '另 113 条 ≥10s 后超时；不当作完整等待样本',
       transform=a.transAxes, ha='center', fontsize=9, color='#6f695f')
for a in axes:
    a.set_facecolor('#f8f5ee')
    a.spines[['top', 'right']].set_visible(False)
    a.grid(axis='y', alpha=.15)
fig.suptitle('exp12 · 总账可以算，分账要有证据；排位不能直接换成秒数', fontsize=14, y=.98)
fig.tight_layout(rect=[0, .09, 1, .94], w_pad=2.2)
out = ROOT / 'phase3b/img/exp12.png'
fig.savefig(out, dpi=170, bbox_inches='tight', facecolor=fig.get_facecolor())
print(out)
