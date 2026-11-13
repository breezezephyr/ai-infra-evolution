"""Audit backend ingress and independent outcome stages; no dropped failures."""
import argparse,csv,hashlib,json
from pathlib import Path
from evaluate import summarize
from gpu_run import identity

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--ingress',type=Path,required=True);a=p.parse_args()
    meta=json.loads((a.run/'summary.json').read_text());plan=json.loads((a.run/'plan.json').read_text());rows=json.loads((a.run/'records.json').read_text())['records']
    for j in plan:assert j['contract']==identity({k:v for k,v in j.items() if k!='contract'}),j['id']
    for n,h in meta['code_sha256'].items():assert hashlib.sha256((a.run/'provenance'/n).read_bytes()).hexdigest()==h,n
    logs=[json.loads(line) for line in a.ingress.read_text().splitlines() if line.strip()]
    logs=[r for r in logs if r.get('run')==meta['run_id']];received={};statuses={}
    for r in logs:
        target=received if r['event']=='request_received' else statuses
        assert r['id'] not in target,'duplicate backend evidence '+r['id'];target[r['id']]=r
    matched=[]
    for r in rows:
        backend=received.get(r['id']);status=statuses.get(r['id'])
        matched.append({'id':r['id'],'received':backend is not None,'body_sha256_match':bool(backend and backend['body_sha256']==r['payload_sha256']),
                        'http_status_match':bool(status and status['status']==r.get('http_status'))})
    reconcile={'n':len(plan),'records':matched,'received':sum(r['received'] for r in matched),'body_matches':sum(r['body_sha256_match'] for r in matched),'status_matches':sum(r['http_status_match'] for r in matched)}
    (a.run.parent/'api-reconciliation.json').write_text(json.dumps(reconcile,ensure_ascii=False,indent=2)+'\n')
    matrix=[]
    for r in rows:
        matrix.append({'id':r['id'],'family':r['family'],'arm':r['arm'],'seed':r['seed'],'http_status':r.get('http_status'),
            'accepted':r.get('accepted'),'finish_reason':r.get('finish_reason'),**{k:r.get('evaluation',{}).get(k) for k in ['json_valid','schema_valid','business_correct','complete','deliverable']},
            'content':r.get('content'),'raw_usage':json.dumps(r.get('response',{}).get('usage'),ensure_ascii=False),'elapsed_ms':r['client_elapsed_ms']})
    with (a.run.parent/'gpu-matrix.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(matrix[0]));w.writeheader();w.writerows(matrix)
    byid={j['id']:j for j in plan}
    wrong=[{'id':r['id'],'task':byid[r['id']]['case']['task'],'expected':byid[r['id']]['case']['expected'],'content':r['content'],'evaluation':r['evaluation']}
           for r in rows if r.get('evaluation',{}).get('schema_valid') and not r['evaluation']['business_correct']]
    report={'run':str(a.run),'overall':summarize(plan,rows),'arms':meta['arms'],'backend_ingress':{k:v for k,v in reconcile.items() if k!='records'},
            'schema_valid_but_wrong_count':len(wrong),'schema_valid_but_wrong_examples':wrong[:8],
            'scope':'Qwen3-0.6B native template / RTX4060 / vLLM0.8.5; 20 synthetic tasks, 2 seeds, single concurrency; no DeepInfer inference, no recipe/Qwen end-to-end integration',
            'denominator_note':'each arm denominator is all 40 planned requests; rejected/unmeasured fields remain null; measured and accepted counts are separate; repeats not independent tasks',
            'matched_supported_subset':{arm:summarize([j for j in plan if j['arm']==arm and j['case']['family']!='ordered_selection'],[r for r in rows if r['arm']==arm and r['family']!='ordered_selection']) for arm in ['prompt_only','json_object','json_schema']},
            'sensitivity_exclude_ambiguous_calc4':{arm:summarize([j for j in plan if j['arm']==arm and j['case']['family']!='ordered_selection' and j['case']['id']!='calc-4'],[r for r in rows if r['arm']==arm and r['family']!='ordered_selection' and r['case_id']!='calc-4']) for arm in ['prompt_only','json_object','json_schema']},
            'prompt_fence_diagnostics':{'parse_failures':sum(r['arm']=='prompt_only' and r.get('evaluation',{}).get('json_valid') is False for r in rows),'failures_starting_code_fence':sum(r['arm']=='prompt_only' and r.get('evaluation',{}).get('json_valid') is False and (r.get('content') or '').lstrip().startswith('```') for r in rows),'repair_applied':False},
            'records_sha256':hashlib.sha256((a.run/'records.json').read_bytes()).hexdigest()}
    (a.run.parent/'gpu-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['schema_valid_but_wrong_examples']},ensure_ascii=False))

if __name__=='__main__':main()
