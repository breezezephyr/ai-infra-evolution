#!/usr/bin/env python3
"""exp11：同义改写的命中率，对上换一词对抗的答错率。"""
import json, os
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
H = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(H, "exp11", "sweep.json")))
for fp in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break
BG, INK, MUTED = "#f8f5ee", "#1c1a17", "#6f695f"
BLUE, RED, GREEN = "#2f5f8a", "#a84d3a", "#4f7a52"
plt.rcParams.update({"axes.facecolor": "#ffffff", "figure.facecolor": BG, "axes.edgecolor": "#e6e0d4",
                     "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 13})
xs = [r["theta"] for r in d["para"]]
fig, ax = plt.subplots(figsize=(10.4, 5.4), dpi=160)
fig.subplots_adjust(left=.08, right=.98, top=.80, bottom=.14)
fig.suptitle("exp11 · 换一个词之后，θ 抬高先伤命中", x=.08, ha="left", fontsize=15, fontweight="bold")
fig.text(.08, .90, "进化之路 · P3b·2 · Qwen3-Embedding-0.6B · 427 句同义改写 · 72 条只换一个区分词", color=MUTED, fontsize=11)
ax.plot(xs, [r["hit_rate"] * 100 for r in d["para"]], color=BLUE, lw=2.2, marker="o", label="同义改写 · 命中率")
ax.plot(xs, [r["wrong_rate"] * 100 for r in d["adv"]], color=RED, lw=2.2, marker="o", label="换一词 · 答错率")
ax.axvline(0.88, color=GREEN, ls="--", lw=1.2)
ax.text(0.805, 52, "θ = 0.88\n同义：答错 0，命中 93%\n换一词：仍有 31% 答错", color=GREEN, fontsize=11)
ax.set_xlim(0.79, 0.99)
ax.set_ylim(-2, 108)
ax.set_xlabel("相似度阈值 θ")
ax.set_ylabel("%")
ax.legend(frameon=False, fontsize=11, loc="center right")
ax.grid(axis="y", color="#eee8dc")
os.makedirs(os.path.join(H, "img"), exist_ok=True)
out = os.path.join(H, "img", "exp11.png")
fig.savefig(out)
print(out)
