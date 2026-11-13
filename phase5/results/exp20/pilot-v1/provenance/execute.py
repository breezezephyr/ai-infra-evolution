"""Frozen fixture backend -> real recipe processor -> local SSE byte replay."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
from stream_run import run_case, identity, pieces, summarize, RESPONSE
from transport import SSEDecoder, frame_events
import deepseek_recipe as recipe

ROOT=Path(__file__).resolve().parent
TOKENIZER_SHA256='81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99'
REQUIRED=['expected_semantic','expected_termination','expected_native_state','expected_probe_error',
          'no_unexpected_error','tool_ids_present_unique','chunk_semantics','sse_byte_roundtrip','sse_incomplete_eof']


def selected(row):
    value=dict(row.get('semantic',{}))
    value['tools']=[{'name':t['name'],'arguments':t['arguments']} for t in value.get('tools',[])]
    return value


def plans(fixtures):
    plan=[]
    for case in fixtures['cases']:
        for protocol in ['chat','responses','messages']:
            for mode in case.get('modes',['text','tokens']):
                for pattern in case.get('patterns',['whole','unit','mixed']):
                    job={'id':f"{case['id']}--{protocol}--{mode}--{pattern}",'case':case,'protocol':protocol,
                         'mode':mode,'pattern':pattern,'required_checks':REQUIRED+(['usage_literal'] if case.get('expect_usage') else [])}
                    job['contract']=identity(job);plan.append(job)
    return plan


def replay_sse(row):
    done=RESPONSE[row['protocol']].sse_done_data() if row.get('native_finished') else None
    events=row.get('events',[]);wire=frame_events(events,done)
    wanted=events+([{'event':None,'data':done}] if done is not None else [])
    # events have only event/data fields; comparisons preserve JSON text exactly.
    observations=[]
    for pattern in ['whole','unit','mixed']:
        decoder=SSEDecoder();found=[]
        for part in pieces(wire,pattern):found.extend(decoder.feed(part))
        found.extend(decoder.finish())
        observations.append({'pattern':pattern,'matched':found==wanted,'event_count':len(found)})
    decoder=SSEDecoder();truncated=decoder.feed(wire[:-1])+decoder.finish() if wire else []
    return dict(bytes=len(wire),sha256=hashlib.sha256(wire).hexdigest(),done_data=done,
                replays=observations,expected_events=len(wanted),incomplete_eof_count=len(truncated),
                incomplete_eof_correct=truncated==wanted[:-1] if wire else truncated==[])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--tokenizer',type=Path,default=ROOT.parent/'vendor/minimal/static/tokenizers/v41/tokenizer.json')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    provenance=args.out/'provenance';provenance.mkdir()
    names=['cases.json','stream_run.py','execute.py','transport.py','test_stream_run.py','test_transport.py']
    for name in names:shutil.copyfile(ROOT/name,provenance/name)
    fixtures=json.loads((provenance/'cases.json').read_text());plan=plans(fixtures)
    (args.out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    assert hashlib.sha256(args.tokenizer.read_bytes()).hexdigest()==TOKENIZER_SHA256,'tokenizer mismatch'
    tokenizer=recipe.Tokenizer.from_file(str(args.tokenizer));rows=[]
    for job in plan:
        case=job['case'];row={}
        try:row=run_case(case,job['protocol'],job['mode'],job['pattern'],tokenizer)
        except Exception as exc:row={'unexpected_error':{'type':type(exc).__name__,'message':str(exc),'stage':'construction/runner'}}
        row.update(id=job['id'],contract=job['contract'],protocol=job['protocol'],mode=job['mode'],pattern=job['pattern'])
        checks=[]
        def check(name,ok,evidence):checks.append({'name':name,'status':'pass' if ok else 'fail','evidence':evidence})
        expected=case['expect'][job['protocol']]
        actual=selected(row);check('expected_semantic',actual==expected,{'actual':actual,'expected':expected})
        check('expected_termination',row.get('termination_source')==case['expect_termination'],row.get('termination_source'))
        check('expected_native_state',row.get('native_finished')==case['expect_native_finished'],row.get('native_finished'))
        expected_error=case.get('expect_error')
        err=row.get('probe_error')
        check('expected_probe_error',bool(err and err['type']=='RuntimeError' and expected_error in err['message']) if expected_error else err is None,err)
        check('no_unexpected_error',row.get('unexpected_error') is None,row.get('unexpected_error'))
        tools=row.get('semantic',{}).get('tools',[]);ids=[t['id'] for t in tools]
        check('tool_ids_present_unique',all(ids) and len(ids)==len(set(ids)) if ids else True,ids)
        try:
            row['sse']=replay_sse(row)
            check('sse_byte_roundtrip',all(x['matched'] for x in row['sse']['replays']),row['sse']['replays'])
            check('sse_incomplete_eof',row['sse']['incomplete_eof_correct'],row['sse']['incomplete_eof_count'])
        except Exception as exc:
            check('sse_byte_roundtrip',False,{'error':str(exc)});check('sse_incomplete_eof',False,{'error':str(exc)})
        if case.get('expect_usage'):
            usage=row.get('response',{}).get('usage');want=case['expect_usage'][job['protocol']]
            check('usage_literal',usage==want,{'actual':usage,'expected':want})
        row['checks']=checks;rows.append(row)
    # Whole-output accumulation is the same native pipeline, not an independent parser.
    baseline={(r['fixture']['id'],r['protocol'],r['mode']):r for r in rows if r.get('fixture') and r['pattern']=='whole'}
    for row in rows:
        case_id=row.get('fixture',{}).get('id');base=baseline.get((case_id,row['protocol'],row['mode']))
        ok=base is not None and not base.get('unexpected_error') and selected(row)==selected(base)
        row['checks'].append({'name':'chunk_semantics','status':'pass' if ok else 'unknown' if base is None else 'fail',
                              'evidence':{'baseline':base.get('id') if base else None,'compared_fields':'text/reasoning/tool name+arguments/finish/status/stop; excludes usage and tool IDs'}})
        (args.out/(row['id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
    (args.out/'records.json').write_text(json.dumps({'records':rows},ensure_ascii=False,indent=2)+'\n')
    report=summarize(plan,rows);report.update(
        source_commit_read='935817c66f5d6e64838f419692545f06787e485f',executed_package=importlib.metadata.version('deepseek-recipe'),
        binary_build_commit=None,python=sys.version,platform=platform.platform(),tokenizer_sha256=TOKENIZER_SHA256,
        fixture_count=len(fixtures['cases']),protocols=['chat','responses','messages'],
        declared_check_counts=dict(Counter(c['status'] for r in rows for c in r['checks'])),
        sse_replay_count=sum(len(r.get('sse',{}).get('replays',[])) for r in rows),
        termination_counts=dict(Counter(r.get('termination_source','unknown') for r in rows)),
        code_sha256={n:hashlib.sha256((provenance/n).read_bytes()).hexdigest() for n in names},
        scope='real recipe native CPU streams; synthetic backend outputs; in-memory SSE byte replay; no model, HTTP network, tool execution or cancellation propagation')
    (args.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'outcomes','code_sha256'}},ensure_ascii=False))
    return 0 if report['failed']==report['unknown']==0 else 1


if __name__=='__main__':sys.exit(main())
