#!/usr/bin/env python3
"""exp12：只回放本地文件。python3 phase3b/exp12/analyze.py

费率固定为示例点数，每千 token 输入/缓存/输出=1/.2/3，不代表服务商价格。
缓存 hits 单位见 README 的 vLLM v0.8.5 源码证据。没有逐请求 usage，不分摊真实 token 账。
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from ledger import reconstruct_queue, split_card_time, token_charge

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'phase3b/results'


def load(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def main():
    sources = []
    def source(path):
        sources.append({'path': str(path.relative_to(ROOT)),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        return path

    runs = []
    proxy_rows = []
    for mode in ['rr', 'hash', 'hash-zipf', 'bounded']:
        path = source(next((ROOT / 'phase3/results').glob(f'exp7-{mode}-20*.json')))
        data = load(path)
        p = sum(s['prompt_tok'] for s in data['servers'].values())
        # 官方 CUDA 默认16；旧记录未保存运行时 block_size。先检查与计数关系相容。
        for server in data['servers'].values():
            tail = server['prompt_tok'] - server['queries'] * 16
            assert 0 <= tail <= server['done'] * 16
        c = sum(s['hits'] for s in data['servers'].values()) * 16
        o = sum(s['gen_tok'] for s in data['servers'].values())
        assert c <= p
        cold = token_charge(p, 0, o)
        charge = token_charge(p, c, o)
        req = jsonl(source(path.with_suffix('.req.jsonl')))
        intervals = [{'id': str(i), 'start': r['t'] + r['ttft_ms'] / 1000,
                      'end': r['t'] + r['e2e_ms'] / 1000}
                     for i, r in enumerate(req) if r.get('ttft_ms') is not None]
        start = min(r['t'] for r in req)
        end = max(r['t'] + r['e2e_ms'] / 1000 for r in req)
        split = split_card_time(intervals, start, end)
        groups = defaultdict(lambda: {'requests': 0, 'decode_overlap_card_s': 0,
                                      'sse_events': 0})
        for i, row in enumerate(req):
            group = groups[str(row['group'])]
            group['requests'] += 1
            group['decode_overlap_card_s'] += split['shares'].get(str(i), 0)
            group['sse_events'] += row['n_out']
            proxy_rows.append({'run': mode, 'row_id': i, 'prefix_group': row['group'],
                               'tenant': None, 'prompt_tokens': None, 'cached_tokens': None,
                               'output_sse_events': row['n_out'],
                               'actual_charge': None,
                               'decode_overlap_card_s': split['shares'].get(str(i), 0)})
        assert abs(sum(s['decode_overlap_card_s'] for s in groups.values()) +
                   split['unassigned_s'] - split['window_s']) < 1e-5
        naive = sum((r['e2e_ms'] - r['ttft_ms']) / 1000 for r in req)
        runs.append({'mode': mode, 'completed': sum(s['done'] for s in data['servers'].values()),
                     'prompt_tokens': p, 'cached_tokens_from_blocks': c, 'output_tokens': o,
                     'cold_price_points': cold, 'cache_price_points': charge,
                     'discount_pct': 100 * (1 - charge / cold),
                     'points_per_1000_completions': charge / len(req) * 1000,
                     'decode_interval_sum_s': naive, 'observed_window_s': split['window_s'],
                     'decode_overlap_allocated_s': sum(split['shares'].values()),
                     'unassigned_s': split['unassigned_s'], 'prefix_groups': dict(groups)})

    # 计费契约样例，手写输入：不是对真实租户观测的补造。
    fixture = [
        {'request_id': 'demo-1', 'tenant': 'A', 'prompt': 1000, 'cached': 0, 'output': 100,
         'outcome': 'ok', 'semantic_hit': False, 'lookup_points': 0},
        {'request_id': 'demo-2', 'tenant': 'A', 'prompt': 1000, 'cached': 800, 'output': 100,
         'outcome': 'ok', 'semantic_hit': False, 'lookup_points': 0},
        {'request_id': 'demo-3', 'tenant': 'B', 'prompt': 1000, 'cached': 800, 'output': 20,
         'outcome': 'aborted', 'semantic_hit': False, 'lookup_points': 0},
        {'request_id': 'demo-4', 'tenant': 'B', 'prompt': 0, 'cached': 0, 'output': 0,
         'outcome': 'ok', 'semantic_hit': True, 'lookup_points': .02},
    ]
    tenants = defaultdict(float)
    for row in fixture:
        row['points'] = token_charge(row['prompt'], row['cached'], row['output']) + row['lookup_points']
        tenants[row['tenant']] += row['points']
    assert abs(sum(tenants.values()) - 2.4) < 1e-9

    queue_path = source(next((ROOT / 'phase3/results').glob('exp5-queue-c32-*.gw.jsonl')))
    q = reconstruct_queue(jsonl(queue_path))
    # 历史 exp1 的既有服务率（本窗口前已知），绝不以本窗口最终完成数校准。
    prior = load(source(next((ROOT / 'phase2/results').glob('exp1-c32-*.json'))))
    mu = prior['request_throughput']
    for row in q:
        row['ahead_reconstructed'] = sum(1 for other in q
              if other['entry'] < row['entry'] and other['exit'] > row['entry'] + .001)
        row['prediction_s'] = (row['ahead_reconstructed'] + 1) / mu
    successful = [r for r in q if r['wait_s'] is not None and r['wait_s'] > .001]
    failed = [r for r in q if r['wait_s'] is None]
    absolute = [abs(r['prediction_s'] - r['wait_s']) for r in successful]
    relative = [abs(r['prediction_s'] - r['wait_s']) / r['wait_s'] for r in successful]
    queue = {'rows': len(q), 'ok': sum(r['wait_s'] is not None for r in q),
             'queued_ok': len(successful), 'censored': len(failed), 'prior_mu': mu,
             'abs_error_p50_s': percentile(absolute, .5), 'abs_error_p90_s': percentile(absolute, .9),
             'relative_error_p50': percentile(relative, .5),
             'within_30pct': sum(e <= .3 for e in relative) / len(relative),
             'censored_predicted_over_10s': sum(r['prediction_s'] > 10 for r in failed),
             'ok_predicted_over_10s': sum(r['prediction_s'] > 10 for r in successful),
             'median_wait_queued_ok_s': median(r['wait_s'] for r in successful),
             'rows_detail': q}
    sweep = load(source(ROOT / 'phase3b/exp11/sweep.json'))
    semantic = []
    for theta in [.88, .98]:
        a = next(x for x in sweep['para'] if x['theta'] == theta)
        b = next(x for x in sweep['adv'] if x['theta'] == theta)
        semantic.append({'theta': theta, 'para_n': a['n'], 'para_hit': a['hit'],
                         'adversarial_n': b['n'], 'adversarial_hit': b['hit'],
                         'adversarial_wrong': b['wrong'],
                         'measured_saved_generation_card_s': None,
                         'embedding_p50_ms': sweep['single']['p50_ms']})
    result = {'kind': 'offline_replay_and_explicit_pricing_model',
              'rates': {'unit': 'demo_points_per_1000_tokens', 'input': 1, 'cached_input': .2, 'output': 3},
              'runs': runs, 'fixture': fixture, 'fixture_tenants': dict(tenants),
              'queue': queue, 'semantic': semantic, 'sources': sources,
              'block_size': 16,
              'source_contract': {
                  'cache_counters_unit': 'blocks',
                  'prompt_counter_includes_cached': True,
                  'block_size_basis': 'official_cuda_default_16_inferred_not_captured_runtime_config',
                  'reference': 'https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/v1/core/kv_cache_manager.py#L147-L161',
                  'prompt_reference': 'https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/v1/metrics/stats.py#L100-L109'}}
    OUT.mkdir(exist_ok=True)
    (OUT / 'exp12-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'exp12-groups.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in proxy_rows))
    (OUT / 'exp12-queue.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in q))
    print('| 路由 | 请求 | 输入 P | 缓存 C | 输出 O | 不折扣点数 | 折扣点数 | 降幅 | 每千次完成点数 |')
    print('|' + '---|' * 9)
    for r in runs:
        print(f"| {r['mode']} | {r['completed']:.0f} | {r['prompt_tokens']:.0f} | {r['cached_tokens_from_blocks']:.0f} | {r['output_tokens']:.0f} | {r['cold_price_points']:.2f} | {r['cache_price_points']:.2f} | {r['discount_pct']:.1f}% | {r['points_per_1000_completions']:.2f} |")
    print('QUEUE', json.dumps({k:v for k,v in queue.items() if k != 'rows_detail'}, ensure_ascii=False))
    for r in runs:
        print('CARD', r['mode'], 'sum', round(r['decode_interval_sum_s'], 2),
              'window', round(r['observed_window_s'], 2), 'allocated', round(r['decode_overlap_allocated_s'], 2),
              'unassigned', round(r['unassigned_s'], 2))


if __name__ == '__main__':
    main()
