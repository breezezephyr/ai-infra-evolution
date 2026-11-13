#!/usr/bin/env python3
"""Static exp14 plots from analyze.py's summary; no fabricated observations.

python3 -B plot.py --summary summary.json --output exp14.png
Requires an existing matplotlib installation; never installs dependencies.
"""
import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS = {'A': '#9aa7b5', 'B': '#4f7a52', 'C': '#c4763a'}
BACKGROUND = '#f8f5ee'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def dots(axis, values, x, color):
    """Deterministic horizontal spread; every dot remains one observed turn."""
    if values:
        offsets = [x + (i - (len(values) - 1) / 2) * min(.04, .5 / len(values))
                   for i in range(len(values))]
        axis.scatter(offsets, values, color=color, s=24, alpha=.8, zorder=3)


def build_figure(summary):
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 5.8), facecolor=BACKGROUND)
    for axis in axes:
        axis.set_facecolor(BACKGROUND)
        axis.spines[['top', 'right']].set_visible(False)
        axis.grid(axis='y', alpha=.13, zorder=0)
        axis.set_xticks(range(3), list('ABC'))
        axis.set_xlim(-.6, 2.6)
    latency, early, render = axes
    points = summary.get('points', [])
    browser = summary.get('browser', {}).get('points', [])
    labels = []
    render_labels = []
    for i, mode in enumerate('ABC'):
        group = summary.get('modes', {}).get(mode, {})
        values = [p['replay_end_to_first_pcm_ms'] for p in points
                  if p.get('mode') == mode and p.get('success') and not p.get('warmup')
                  and finite(p.get('replay_end_to_first_pcm_ms'))]
        dots(latency, values, i, COLORS[mode])
        stats = group.get('replay_end_to_first_pcm_ms', {})
        if stats.get('n', 0) and finite(stats.get('p50')):
            latency.plot([i - .23, i + .23], [stats['p50']] * 2, color=COLORS[mode], lw=2.5)
        valid_cases = {p.get('case_id') for p in points if p.get('mode') == mode
                       and p.get('success') and not p.get('warmup')}
        labels.append(f'{mode}\nvalid n={len(values)}\ncases={len(valid_cases)}')
        n = group.get('n', 0)
        if n:
            value = group['counts']['early']
            early.bar(i, value, color=COLORS[mode], width=.6, zorder=2)
            unknown = group['counts'].get('early_unknown', 0)
            early.annotate(f'{value}/{n}\nunknown={unknown}', (i, value), xytext=(0, 6),
                           textcoords='offset points', ha='center', fontsize=9)
        render_values = [p['first_non_silent_render_ms'] for p in browser
                         if p.get('mode') == mode and p.get('success') and not p.get('warmup')
                         and finite(p.get('first_non_silent_render_ms'))]
        dots(render, render_values, i, COLORS[mode])
        render_labels.append(f'{mode}\nn={len(render_values)}')
    latency.set_xticks(range(3), labels)
    render.set_xticks(range(3), render_labels)
    latency.set_title('Replay end to first PCM', pad=13)
    latency.set_ylabel('Client same-clock latency / ms')
    latency.text(.5, -.32, 'Valid turns only; dots = repeats, line = p50',
                 transform=latency.transAxes, ha='center', fontsize=8, color='#6f695f')
    early.set_title('Early endpoints / all measured turns', pad=13)
    early.set_ylabel('Early endpoint count')
    max_early = max((g.get('counts', {}).get('early', 0)
                     for g in summary.get('modes', {}).values()), default=0)
    early.set_ylim(0, max(1, max_early * 1.4 + 1))
    early.text(.5, -.32, '12 inputs x 3 repeats; early endpoints can also end in stop',
               transform=early.transAxes, ha='center', fontsize=8, color='#6f695f')
    render.set_title('Browser first non-silent render', pad=13)
    render.set_ylabel('Browser same-clock latency / ms')
    render.text(.5, -.32, 'One short input; render is separate from acoustic sound',
                transform=render.transAxes, ha='center', fontsize=8, color='#6f695f')
    for axis in (latency, render):
        if not axis.collections:
            axis.text(.5, .5, 'No measured observations', transform=axis.transAxes,
                      ha='center', color='#6f695f')
    if not early.patches:
        early.text(.5, .5, 'No measured turns', transform=early.transAxes, ha='center', color='#6f695f')
    fig.suptitle('exp14 · observed latency and early endpoints', fontsize=14, y=.98)
    fig.tight_layout(rect=[0, .1, 1, .94], w_pad=2.3)
    return fig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.summary.resolve() == args.output.resolve():
        parser.error('output must not overwrite summary')
    data = json.loads(args.summary.read_text(encoding='utf-8'))
    fig = build_figure(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=170, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(args.output)


if __name__ == '__main__':
    main()
