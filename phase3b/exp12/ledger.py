"""exp12：离线账本。计费点是教学单位；卡秒是流重叠分摊代理。"""
from collections import defaultdict


def token_charge(prompt, cached, output, rates=(1.0, 0.2, 3.0)):
    """cached 是 prompt 子集。未知不记零；价格为每千 token 的示例点数。"""
    if prompt is None or cached is None or output is None:
        return None
    if min(prompt, cached, output, *rates) < 0 or cached > prompt:
        raise ValueError('token 数与费率必须非负，cached 不得超过 prompt')
    a, b, c = rates
    return ((prompt - cached) * a + cached * b + output * c) / 1000


def split_card_time(rows, start, end):
    """一张卡，多个重叠生成流等分时间。非核函数追踪，不是能耗实测。

    rows: id/start/end。裁剪到指定窗口；不允许同一 id 重复。
    """
    if end < start:
        raise ValueError('窗口结束早于开始')
    events = defaultdict(lambda: {'add': [], 'remove': []})
    shares = {}
    for row in rows:
        key = row['id']
        if key in shares or row['end'] < row['start']:
            raise ValueError('重复 id 或负时长')
        shares[key] = 0.0
        a, b = max(start, row['start']), min(end, row['end'])
        if b > a:
            events[a]['add'].append(key)
            events[b]['remove'].append(key)
    events[start]; events[end]
    active = set()
    previous = start
    unassigned = 0.0
    for t, event in sorted(events.items()):
        dt = t - previous
        if active:
            for key in active:
                shares[key] += dt / len(active)
        else:
            unassigned += dt
        active.difference_update(event['remove'])
        active.update(event['add'])
        previous = t
    return {'shares': shares, 'unassigned_s': unassigned, 'window_s': end - start}


def reconstruct_queue(rows):
    """从日志写入时刻反推网关入队/出队时刻；时间精度约 ms。

    timeout 的真实准入等待未知，保留右删失，不把 10s 当最终等待。
    """
    result = []
    for i, row in enumerate(rows):
        outcome = row['outcome']
        if outcome not in ('ok', 'queue_timeout'):
            continue
        q = row['queue_ms'] / 1000
        exit_time = row['ts'] - (row['total_ms'] / 1000 if outcome == 'ok' else 0)
        result.append({'id': i, 'entry': exit_time - q, 'exit': exit_time,
                       'end': row['ts'], 'outcome': outcome,
                       'wait_s': q if outcome == 'ok' else None,
                       'lower_bound_s': q if outcome != 'ok' else None})
    return result
