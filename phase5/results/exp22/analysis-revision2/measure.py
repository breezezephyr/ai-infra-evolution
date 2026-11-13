"""Bounded admission and measurement contracts for exp22."""
import threading
import time
import hashlib
import json


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


def compare_outputs(rows, outputs, verified_ids=None, baseline_ids=None):
    result=dict(planned=len(rows),http_accepted=0,with_token_ids=0,
                missing_token_ids=0,compared_to_baseline=0,equal=0,different=0)
    baselines={} if baseline_ids is None else {task:outputs[identity]['token_ids']
        for task,identity in baseline_ids.items() if identity in outputs and
        (verified_ids is None or identity in verified_ids)}
    if verified_ids is not None:
        result['evidence_verified']=0
    if baseline_ids is not None:
        result['missing_baseline']=0
    for row in rows:
        if row['status'] != 200:
            continue
        result['http_accepted'] += 1
        if verified_ids is not None:
            if row['id'] not in verified_ids:continue
            result['evidence_verified']+=1
        output=outputs.get(row['id'])
        if output is None or 'token_ids' not in output:
            result['missing_token_ids'] += 1
            continue
        ids=output['token_ids']
        result['with_token_ids'] += 1
        task=row['task']
        if baseline_ids is not None:
            if task not in baselines:
                result['missing_baseline']+=1
                continue
            if row['id']==baseline_ids[task]:continue
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


def validate_record(row, gateway, backend, payload, config):
    issues=reconcile(row,gateway,backend)
    identity=row['id'];internal='chatcmpl-'+identity
    request=[e for e in backend if e.get('event')=='engine_request' and e.get('request_id')==internal]
    done=[e for e in backend if e.get('event')=='api_finished' and e.get('id')==identity]
    outputs=[e for e in backend if e.get('event')=='engine_finished' and e.get('request_id')==internal]
    if len(request)!=1:issues.append('engine_request_count')
    if len(done)!=1:issues.append('api_finished_count')
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if row['body_sha256']!=digest:issues.append('plan_body_sha256')
    response=row.get('response') or {}
    if response.get('id')!=internal:issues.append('response_id')
    if response.get('model')!=payload['model']:issues.append('response_model')
    if len(request)==1:
        expected={k:payload[k] for k in ['temperature','top_p','top_k','seed','max_tokens']};expected['n']=1
        if request[0].get('settings')!=expected:issues.append('sampling_settings')
        if request[0].get('effective_config')!=config:issues.append('effective_config')
    if len(outputs)==1:
        output=outputs[0];ids=output.get('prompt_token_ids',[]);choices=output.get('outputs',[])
        actual=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
        if not ids or not all(type(i)is int for i in ids) or actual!=output.get('prompt_ids_sha256'):issues.append('prompt_ids_sha256')
        if len(choices)!=1 or len(response.get('choices',[]))!=1:issues.append('output_count')
        else:
            o=choices[0];api=response['choices'][0]
            usage=response.get('usage',{});expected_usage={'prompt_tokens':len(ids),'completion_tokens':len(o['token_ids']),'total_tokens':len(ids)+len(o['token_ids'])}
            if any(usage.get(k)!=v for k,v in expected_usage.items()):issues.append('usage')
            if api.get('message',{}).get('content')!=o['text'] or api.get('finish_reason')!=o['finish_reason']:issues.append('response_output')
    return issues


def clock_discontinuity(metrics, start_ns, finish_ns, tolerance_ms=100):
    """Flag inconsistent observed intervals, without attempting clock repair."""
    if metrics.get('finished_time') is None:return True
    wall_ms=(metrics['finished_time']-metrics['arrival_time'])*1000
    mono_ms=(finish_ns-start_ns)/1e6
    return abs(wall_ms-mono_ms)>tolerance_ms
