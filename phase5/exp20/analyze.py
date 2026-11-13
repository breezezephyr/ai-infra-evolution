"""Publish the declared experiment matrix; keep raw protocol usage separate."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from stream_run import summarize


def raw_arguments(row):
    values={};protocol=row['protocol']
    for frame in row.get('events',[]):
        event=json.loads(frame['data'])
        if protocol=='chat':
            for choice in event.get('choices',[]):
                for t in choice.get('delta',{}).get('tool_calls',[]) or []:
                    key=str(t['index']);values[key]=values.get(key,'')+t.get('function',{}).get('arguments','')
        elif protocol=='responses' and event.get('type')=='response.function_call_arguments.delta':
            key=str(event['output_index']);values[key]=values.get(key,'')+event.get('delta','')
        elif protocol=='messages' and event.get('type')=='content_block_delta' and event.get('delta',{}).get('type')=='input_json_delta':
            key=str(event['index']);values[key]=values.get(key,'')+event['delta'].get('partial_json','')
    return values


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path);args=parser.parse_args()
    run=args.run;meta=json.loads((run/'summary.json').read_text());plan=json.loads((run/'plan.json').read_text())
    for name,digest in meta['code_sha256'].items():
        assert hashlib.sha256((run/'provenance'/name).read_bytes()).hexdigest()==digest,name
    rows=json.loads((run/'records.json').read_text())['records'];summary=summarize(plan,rows)
    matrix=[]
    for r in rows:
        matrix.append(dict(id=r['id'],fixture=r['fixture']['id'],protocol=r['protocol'],mode=r['mode'],pattern=r['pattern'],
            termination_source=r.get('termination_source'),backend_finish_seen=r.get('backend_finish_seen'),native_finished=r.get('native_finished'),
            finish=r.get('semantic',{}).get('finish'),events=len(r.get('events',[])),
            tool_argument_deltas=json.dumps(raw_arguments(r),ensure_ascii=False),
            final_tools=json.dumps(r.get('semantic',{}).get('tools',[]),ensure_ascii=False),
            raw_usage=json.dumps(r.get('response',{}).get('usage'),ensure_ascii=False),
            usage_sources=json.dumps(r.get('usage_sources'),ensure_ascii=False),
            unsubmitted_units=r.get('unsubmitted_units'),
            expected_probe_error=json.dumps(r.get('probe_error'),ensure_ascii=False),
            failed_checks=sum(c['status']=='fail' for c in r['checks'])))
    with (run.parent/'capability-matrix.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    evidence={}
    for fixture,mode in [('thinking_answer','text'),('text_with_tokenizer','text_tokenizer'),('thinking_answer','tokens'),
                         ('missing_finish','text'),('client_close','text'),('unfinished_tool','text'),('stop_sequence','tokens')]:
        for protocol in ['chat','responses','messages']:
            r=next(r for r in rows if r['fixture']['id']==fixture and r['mode']==mode and r['protocol']==protocol and r['pattern']=='whole')
            evidence[f'{fixture}/{protocol}/{mode}']={k:r.get(k) for k in ['id','semantic','response','termination_source','backend_finish_seen','native_finished','usage_sources','unsubmitted_units','sse']}
            evidence[f'{fixture}/{protocol}/{mode}']['raw_argument_deltas']=raw_arguments(r)
    report={**summary,'run':str(run),'experiment':meta,'representative_evidence':evidence,
            'comparison_boundary':'same native processor and accumulator, varied chunking; content/finish compare excludes usage, tool IDs and timestamps',
            'counts_note':'19 fixture definitions expanded to 222 configured streams; 2004 repeated declared checks; 666 local byte replays reuse those events; not model calls or independent capabilities',
            'record_sha256':hashlib.sha256((run/'records.json').read_bytes()).hexdigest()}
    (run.parent.parent/'exp20-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['n','passed','failed','unknown']},ensure_ascii=False))


if __name__=='__main__':main()
