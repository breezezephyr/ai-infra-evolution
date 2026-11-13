"""Join independent client/gateway/API/engine observations without clock mixing."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from collections import Counter,defaultdict
from measure import compare_outputs, engine_durations, reconcile


def percentile(values, fraction):
    return sorted(values)[max(0,math.ceil(len(values)*fraction)-1)] if values else None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--backend',required=True)
    args=parser.parse_args();root=Path(args.directory)
    plan=json.loads((root/'plan.json').read_text())
    rows=sorted(json.loads((root/'records.json').read_text()),key=lambda r:(r['batch'],r['id']))
    gateway=[json.loads(x) for x in (root/'gateway.jsonl').read_text().splitlines()]
    all_backend=[json.loads(x) for x in Path(args.backend).read_text().splitlines()]
    backend=[e for e in all_backend if plan['run_id'] in e.get('id','') or plan['run_id'] in e.get('request_id','')]
    expected={f"{plan['run_id']}-b{i:02d}-i{j}" for i,b in enumerate(plan['batches']) for j in range(len(b['tasks']))}
    observed=[r['id'] for r in rows]
    assert set(observed)==expected and len(observed)==len(expected), 'missing/duplicate/unplanned client rows'
    outputs={};matrix=[];issues=[];prompt_hashes=defaultdict(set)
    request_ids={'chatcmpl-'+r['id'] for r in rows}
    batch_sizes=defaultdict(list);plans=[]
    for e in all_backend:
        if e['event']=='scheduler_plan':
            ids=[g['request_id'] for g in e['groups']]
            if request_ids.intersection(ids):
                plans.append(e)
                for identity in ids:
                    if identity in request_ids:batch_sizes[identity].append(len(ids))
    by_engine={e['request_id']:e for e in backend if e['event']=='engine_finished'}
    by_gateway={e['id']:e for e in gateway}
    baseline={}
    for r in rows:
        g=by_gateway.get(r['id']);engine=by_engine.get('chatcmpl-'+r['id'])
        check=reconcile(r,gateway,backend) if r['status']==200 else ['not_accepted']
        if check:issues.append({'id':r['id'],'issues':check})
        item={k:r[k] for k in ['id','task','kind','mode','concurrency','repeat','status','error']}
        item.update(driver_wait_ms=(r['started_ns']-r['submitted_ns'])/1e6,
                    client_response_ms=(r['finished_ns']-r['started_ns'])/1e6,
                    submitted_to_response_ms=(r['finished_ns']-r['submitted_ns'])/1e6,
                    gateway_wait_ms=g.get('gateway_wait_ms') if g else None,
                    max_observed_batch=max(batch_sizes.get('chatcmpl-'+r['id'],[0])),
                    verification_issues=','.join(check))
        if r['status']==200 and engine:
            assert len(engine['outputs'])==1
            o=engine['outputs'][0];outputs[r['id']]=o;prompt_hashes[r['task']].add(engine['prompt_ids_sha256'])
            assert engine['metrics'] is not None
            item.update(engine_durations(engine['metrics']))
            item.update(prompt_tokens=len(engine['prompt_token_ids']),output_tokens=len(o['token_ids']),finish_reason=o['finish_reason'])
            # API text must equal the final engine text; no response repair.
            item['api_text_matches_engine']=r['response']['choices'][0]['message']['content']==o['text']
            item['api_usage_matches_ids']=r['response']['usage']['completion_tokens']==len(o['token_ids'])
            if not item['api_text_matches_engine'] or not item['api_usage_matches_ids']:
                issues.append({'id':r['id'],'issues':['response_output_mismatch']})
            if r['task'] not in baseline:baseline[r['task']]=o['token_ids']
            ids=o['token_ids'];ref=baseline[r['task']]
            item['same_as_solo_baseline']=ids==ref
            item['first_different_token_index']=next((i for i,(a,b) in enumerate(zip(ids,ref)) if a!=b),min(len(ids),len(ref)) if ids!=ref else None)
        matrix.append(item)
    groups=[]
    for mode in ['direct','bounded']:
        for concurrency in [1,2,4]:
            m=[r for r in matrix if r['mode']==mode and r['concurrency']==concurrency]
            batches=[b for b in json.loads((root/'batch-times.json').read_text()) if b['mode']==mode and b['concurrency']==concurrency]
            result={'mode':mode,'concurrency':concurrency,'planned':len(m),'accepted':sum(r['status']==200 for r in m),
                    'batch_makespan_median_ms':statistics.median(b['elapsed_ms'] for b in batches),
                    'generated_tokens':sum(r.get('output_tokens',0) for r in m),
                    'max_observed_batch':max(r['max_observed_batch'] for r in m)}
            for key in ['driver_wait_ms','gateway_wait_ms','client_response_ms','queue_ms','first_token_ms','scheduled_to_finish_ms']:
                vals=[r[key] for r in m if r.get(key) is not None]
                result[key]={'n':len(vals),'median':statistics.median(vals) if vals else None,'p95_nearest_rank':percentile(vals,.95)}
            groups.append(result)
    comparison=compare_outputs(rows,outputs)
    mixed=[r for r in matrix if r['max_observed_batch']>1 and r.get('same_as_solo_baseline') is not None]
    summary={'run_id':plan['run_id'],'planned':len(expected),'status_counts':dict(Counter(str(r['status']) for r in rows)),
             'verification_issues':issues,'input_ids_stable':all(len(v)==1 for v in prompt_hashes.values()),
             'tasks_with_ids':len(prompt_hashes),'comparison':comparison,
             'mixed_batch_observations':len(mixed),'mixed_batch_equal_to_solo':sum(r['same_as_solo_baseline'] for r in mixed),
             'scheduler_plan_count':len(plans),'batch_size_histogram':dict(Counter(len(p['groups']) for p in plans)),
             'finish_reasons':dict(Counter(r.get('finish_reason') for r in matrix)),
             'groups':groups,'effective_configs':[e['effective_config'] for e in backend if e['event']=='engine_request'][:1],
             'clock_rule':'only subtract timestamps from the same clock domain; nonstream client response time is not TTFT',
             'scope':'Qwen3-0.6B on instrumented vLLM0.8.5 V0/eager; free greedy generation, no teacher forcing; not DeepInfer execution',
             'data_sha256':{f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in ['plan.json','records.json','gateway.jsonl']}}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    fields=list(dict.fromkeys(k for r in matrix for k in r))
    with (root/'matrix.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(matrix)
    (root/'joined.json').write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['planned','status_counts','verification_issues','input_ids_stable','comparison','mixed_batch_observations','mixed_batch_equal_to_solo','batch_size_histogram','finish_reasons']},ensure_ascii=False))


if __name__=='__main__':main()
