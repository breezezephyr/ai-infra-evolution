"""Bounded admission and measurement contracts for exp22."""
import threading
import time


class Overloaded(Exception):
    pass


class Ticket:
    def __init__(self, gate, wait_ms):
        self.gate, self.wait_ms, self.released = gate, wait_ms, False

    def release(self):
        with self.gate.condition:
            if not self.released:
                self.released = True
                self.gate.active -= 1
                self.gate.condition.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


class Admission:
    """Capacity gate. Waiting order is unspecified; overflow is explicit."""
    def __init__(self, active_limit, waiting_limit):
        if active_limit < 1 or waiting_limit < 0:
            raise ValueError('invalid capacity')
        self.active_limit, self.waiting_limit = active_limit, waiting_limit
        self.active = self.waiting = 0
        self.condition = threading.Condition()

    def snapshot(self):
        with self.condition:
            return {'active':self.active, 'waiting':self.waiting}

    def enter(self):
        start = time.monotonic()
        with self.condition:
            if self.active >= self.active_limit:
                if self.waiting >= self.waiting_limit:
                    raise Overloaded('admission queue full')
                self.waiting += 1
                try:
                    while self.active >= self.active_limit:
                        self.condition.wait()
                finally:
                    self.waiting -= 1
            self.active += 1
        return Ticket(self, (time.monotonic()-start)*1000)


def engine_durations(metrics):
    arrival = metrics['arrival_time']
    scheduled, first, finish = (metrics.get(k) for k in
        ('first_scheduled_time','first_token_time','finished_time'))
    return {
        'queue_ms':None if scheduled is None else (scheduled-arrival)*1000,
        'first_token_ms':None if first is None else (first-arrival)*1000,
        'scheduled_to_finish_ms':None if finish is None or scheduled is None else (finish-scheduled)*1000,
        'total_ms':None if finish is None else (finish-arrival)*1000,
    }


def compare_outputs(rows, outputs):
    result=dict(planned=len(rows),http_accepted=0,with_token_ids=0,
                missing_token_ids=0,compared_to_baseline=0,equal=0,different=0)
    baselines={}
    for row in rows:
        if row['status'] != 200:
            continue
        result['http_accepted'] += 1
        output=outputs.get(row['id'])
        if output is None or 'token_ids' not in output:
            result['missing_token_ids'] += 1
            continue
        ids=output['token_ids']
        result['with_token_ids'] += 1
        task=row['task']
        if task not in baselines:
            baselines[task]=ids
        else:
            result['compared_to_baseline'] += 1
            result['equal' if ids == baselines[task] else 'different'] += 1
    return result


def reconcile(row, gateway, backend):
    """For accepted rows require exactly one observation at every boundary."""
    identity=row['id'];issues=[]
    g=[e for e in gateway if e.get('id')==identity]
    ingress=[e for e in backend if e.get('event')=='api_ingress' and e.get('id')==identity]
    responses=[e for e in backend if e.get('event')=='api_response' and e.get('id')==identity]
    finished=[e for e in backend if e.get('event')=='engine_finished' and e.get('request_id')=='chatcmpl-'+identity]
    for label,values in [('gateway_count',g),('ingress_count',ingress),('response_count',responses),('engine_count',finished)]:
        if len(values)!=1:issues.append(label)
    if any(e.get('body_sha256')!=row['body_sha256'] for e in g+ingress):issues.append('body_sha256')
    if any(e.get('status')!=row['status'] for e in g+responses):issues.append('http_status')
    return issues
