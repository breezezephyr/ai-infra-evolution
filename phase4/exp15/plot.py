#!/usr/bin/env python3
"""Render the validated exp15 v2 summary. Offline, CPU-only matplotlib.

/tmp/exp14-local-env/bin/python -B phase4/exp15/plot.py
Only writes phase4/img/exp15.png; --vector also writes that figure's SVG/PDF.
"""
import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

PHASE4 = Path(__file__).resolve().parents[1]
SUMMARY = PHASE4 / 'results' / 'exp15-summary.json'
OUTPUT = PHASE4 / 'img' / 'exp15.png'
BACKGROUND = '#f8f5ee'
INK = '#292e33'
MUTED = '#6f695f'
BLUE = '#487da2'
ORANGE = '#c4763a'
GREEN = '#4f7a52'
RULE = '#ddd6c8'


def configure_fonts():
    for path in ('/System/Library/Fonts/Hiragino Sans GB.ttc',
                 '/System/Library/Fonts/STHeiti Medium.ttc'):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams['font.family'] = font_manager.FontProperties(fname=path).get_name()
            break
    plt.rcParams.update({'axes.unicode_minus': False, 'font.size': 10, 'font.weight': 300,
                         'axes.labelweight': 300, 'axes.titleweight': 600,
                         'text.color': INK, 'axes.labelcolor': MUTED,
                         'xtick.color': MUTED, 'ytick.color': INK,
                         'svg.fonttype': 'path', 'pdf.fonttype': 42})


def fmt(value, digits=1):
    return f'{value:,.{digits}f}' if type(value) in (int, float) and math.isfinite(value) else '缺失'


def group(summary, scenario, transport, fixture):
    return next(g for g in summary['formal']['groups'] if
                (g['scenario'], g['transport'], g['fixture_id']) == (scenario, transport, fixture))


def title(axis, letter, text, subtitle):
    axis.text(0, 1.13, letter, transform=axis.transAxes, fontsize=15, weight=600, color=GREEN)
    axis.text(.075, 1.13, text, transform=axis.transAxes, fontsize=13.5, weight=600)
    axis.text(0, 1.055, subtitle, transform=axis.transAxes, fontsize=9, color=MUTED)


def latency_panel(axis, summary):
    title(axis, 'A', '本机起播观察', 'baseline · 两段固定音频，各重复 3 次')
    rows = [('ws', 'short'), ('ws', 'long'), ('rtc', 'short'), ('rtc', 'long')]
    labels, maxima = [], []
    for i, (transport, fixture) in enumerate(rows):
        g = group(summary, 'baseline', transport, fixture)
        stats = g['metrics']['start_to_first_render_ms']
        values, median = stats['values'], stats['p50']
        color = BLUE if transport == 'ws' else ORANGE
        y = 3 - i
        for j, value in enumerate(values):
            if value is not None:
                axis.scatter(value, y + (j - 1) * .10, s=40, color=color, alpha=.85, zorder=3)
        axis.plot([median, median], [y - .24, y + .24], color=color, lw=2.5, zorder=4)
        axis.text(median + 4, y + .26, f'p50 {median:.1f}', color=color, fontsize=10)
        labels.append(f'{"WS" if transport == "ws" else "RTC"} · {"短" if fixture == "short" else "长"}\n'
                      f'n={g["n_complete"]}，失败 {g["n_failed"]}')
        maxima.extend(values)
    axis.set_yticks(range(3, -1, -1), labels, fontsize=9)
    axis.set_ylim(-.5, 3.65)
    axis.set_xlim(0, max(maxima) * 1.30 + 7)
    axis.set_xlabel('start_to_first_render_ms / ms', fontsize=9, labelpad=10)
    axis.spines[['top', 'right', 'left']].set_visible(False)
    axis.spines['bottom'].set_color(RULE)
    axis.tick_params(axis='y', length=0, pad=8)
    axis.grid(axis='x', color=RULE, lw=.7, zorder=0)
    axis.axhline(1.5, color=RULE, lw=.8)
    axis.text(0, -.23, '圆点＝逐次观察；竖线＝中位数', transform=axis.transAxes, fontsize=9, color=MUTED)
    paths = summary['formal']['rtc_paths']
    observed = sorted({f'{p["local_protocol"]} {p["local_type"]}/{p["remote_type"]}' for p in paths})
    codecs = sorted({p['codec']['mimeType'] or 'codec 缺失' for p in paths})
    axis.text(0, -.34, 'WS：48 kHz PCM / TCP\nRTC：' + '、'.join(codecs) + ' / ' + '、'.join(observed),
              transform=axis.transAxes, fontsize=9, color=MUTED, linespacing=1.6)


def metric_table(axis, summary, transport, metric, top, color, snapshot=False):
    """Two independent tables; RTC samples never share WS duration's axis."""
    axis.text(.45, top, '短音频', ha='center', fontsize=9, color=MUTED)
    axis.text(.80, top, '长音频', ha='center', fontsize=9, color=MUTED)
    for j, scenario in enumerate(('baseline', 'source_pause')):
        y = top - .105 - j * .12
        axis.text(.02, y, '基线' if scenario == 'baseline' else '源暂停', fontsize=10)
        for fixture, x in (('short', .45), ('long', .80)):
            g = group(summary, scenario, transport, fixture)
            stats = g['rtc_end_snapshot'][metric] if snapshot else g['metrics'][metric]
            digits = 0 if snapshot else 1
            axis.text(x, y, fmt(stats['p50'], digits), ha='center', fontsize=13, weight=600, color=color)
    axis.plot([0, .99], [top - .15] * 2, color=RULE, lw=.7)


def pause_panel(axis, summary):
    title(axis, 'B', '源供给暂停 200ms', '每格 n=3，显示 p50；两种定义分别展示')
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis('off')
    axis.text(0, .93, 'WS · 播放队列欠载 / ms', color=BLUE, fontsize=11, weight=600)
    metric_table(axis, summary, 'ws', 'ws_underrun_ms', .83, BLUE)
    axis.text(0, .46, 'RTC · concealedSamples / 样本', color=ORANGE, fontsize=11, weight=600)
    axis.text(0, .395, '结束累计快照诊断；不充当起止差分', color=MUTED, fontsize=9)
    metric_table(axis, summary, 'rtc', 'concealedSamples', .30, ORANGE, snapshot=True)
    missing = summary['formal']['integrity']['rtc_missing_inbound_start_n']
    axis.text(0, -.23, f'{missing}/12 次缺起始 inbound-rtp：区间差分＝null',
              transform=axis.transAxes, fontsize=9, color=MUTED)
    axis.text(0, -.34, '源暂停没有注入网络丢包。\nWS 欠载时长与 RTC 掩盖样本不作等量比较。',
              transform=axis.transAxes, fontsize=9, color=MUTED, linespacing=1.6)


def drain_panel(axis, summary):
    drain = summary['browser_drain']
    title(axis, 'C', '发送完成之后，仍须排空', f'独立浏览器样例 · 起播缓冲 {drain["initial_buffer_ms"]}ms · n={drain["n"]}')
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis('off')
    axis.text(.5, .81, f'{drain["producer_to_finished_ms"]:.1f}', ha='center', fontsize=39, weight=600, color=GREEN)
    axis.text(.5, .70, 'ms', ha='center', fontsize=13, color=GREEN)
    axis.annotate('', xy=(.90, .52), xytext=(.10, .52),
                  arrowprops={'arrowstyle': '->', 'lw': 2.4, 'color': GREEN})
    axis.scatter([.10, .90], [.52, .52], s=55, color=[BLUE, GREEN], zorder=3)
    axis.text(.10, .45, 'producer_done\n主线程观察到', ha='left', va='top', fontsize=9, linespacing=1.6)
    axis.text(.90, .45, 'finished\nWorklet 渲染完成通知', ha='right', va='top', fontsize=9, linespacing=1.6)
    axis.add_patch(FancyBboxPatch((.05, .05), .90, .20, boxstyle='round,pad=0.02',
                                  linewidth=0, facecolor='#e8ecdf'))
    axis.text(.5, .17, f'{drain["rendered_samples"]:,} 个样本已由 Worklet 消费',
              ha='center', fontsize=11, color=GREEN, weight=600)
    axis.text(.5, .09, 'ACK → release → worker drained', ha='center', fontsize=9, color=MUTED)
    axis.text(0, -.23, f'发送完成时最近报告尚未渲染 {drain["latest_report_unrendered_samples_at_producer_observation"]:,} 样本',
              transform=axis.transAxes, fontsize=9, color=MUTED)
    axis.text(0, -.34, '最近报告有时间粒度，不是瞬时精确队列。\n该例测量渲染通知，未做声学回环。',
              transform=axis.transAxes, fontsize=9, color=MUTED, linespacing=1.6)


def validate_summary(summary):
    if summary.get('schema_version') != 'exp15.v2':
        raise ValueError('plot requires the validated v2 summary')
    formal = summary['formal']
    integrity = formal['integrity']
    if not (summary['config'].get('endedAt') and formal['n'] == formal['n_complete'] == 24
            and formal['n_failed'] == 0 and integrity['source_supply_complete_n'] == 24
            and integrity['ws_all_samples_consumed_n'] == 12
            and integrity['rtc_producer_done_received_n'] == integrity['rtc_probe_near_expected_end_n'] == 12):
        raise ValueError('formal completion/integrity gate not satisfied')
    for g in formal['groups']:
        if g['n_complete'] != 3 or g['n_failed'] != 0:
            raise ValueError('incomplete three-repeat cell')


def build_figure(summary):
    validate_summary(summary)
    configure_fonts()
    fig = plt.figure(figsize=(17.2, 7.7), facecolor=BACKGROUND)
    grid = fig.add_gridspec(1, 3, left=.085, right=.97, bottom=.32, top=.76,
                           width_ratios=[1.07, 1, 1], wspace=.33)
    axes = [fig.add_subplot(grid[0, i]) for i in range(3)]
    for axis in axes:
        axis.set_facecolor(BACKGROUND)
    latency_panel(axes[0], summary)
    pause_panel(axes[1], summary)
    drain_panel(axes[2], summary)
    fig.text(.055, .945, 'exp15  ·  音频传输与会话排空', fontsize=23, weight=600)
    fig.text(.055, .893, '本机正式 v2：2 段音频 × 2 传输 × 2 场景 × 3 次重复；24/24 complete，失败 0',
             fontsize=10.5, color=MUTED)
    fig.text(.055, .088, '起播＝主线程收到首个非静音 AudioWorklet 通知的 performance 差，含消息派发；固定回放含首尾探针。',
             fontsize=9.5, color=MUTED)
    fig.text(.055, .049, 'WS：12/12 源样本接收＝消费。RTC：12/12 源供给完整、尾探针＋250ms guard＋producer_done；不承诺逐样本 ACK。',
             fontsize=9.5, color=MUTED)
    return fig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vector', action='store_true', help='also save exp15.svg and exp15.pdf')
    args = parser.parse_args(argv)
    summary = json.loads(SUMMARY.read_text(encoding='utf-8'))
    fig = build_figure(summary)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=180, facecolor=BACKGROUND)
    if args.vector:
        for extension in ('.svg', '.pdf'):
            fig.savefig(OUTPUT.with_suffix(extension), facecolor=BACKGROUND)
    plt.close(fig)
    print(OUTPUT)


if __name__ == '__main__':
    main()
