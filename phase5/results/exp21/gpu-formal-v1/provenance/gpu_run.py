"""Sequential real-model experiment; save every attempt without repairing text."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
import urllib.error
from evaluate import evaluate,summarize
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parent
def identity(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def payload(case,arm,seed,model,settings):
    prompt=case['task']+'\n只输出符合以下JSON Schema的JSON，不加解释或代码围栏：\n'+json.dumps(case['schema'],ensure_ascii=False)
    body={'model':model,'messages':[{'role':'system','content':'根据输入完成任务，保持事实与计算准确，只输出要求的JSON。'},{'role':'user','content':prompt}],**settings,'seed':seed,'stream':False}
    if arm=='json_object':body['response_format']={'type':'json_object'}
    if arm=='json_schema':body['response_format']={'type':'json_schema','json_schema':{'name':'exp21_result','strict':True,'schema':case['schema']}}
    return body

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--thinking-disabled',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    prov=a.out/'provenance';prov.mkdir()
    for n in ['gpu-cases.json','gpu_run.py','evaluate.py','backend_audit.py']:shutil.copyfile(ROOT/n,prov/n)
    fixture=json.loads((prov/'gpu-cases.json').read_text());settings=fixture['generation'].copy();settings['guided_decoding_backend']='xgrammar:no-fallback'
    if a.thinking_disabled:settings['chat_template_kwargs']={'enable_thinking':False}
    plan=[]
    for seed in fixture['seeds']:
        for case in fixture['cases']:
            Draft202012Validator.check_schema(case['schema']);Draft202012Validator(case['schema']).validate(case['expected'])
            # Counterbalance arm order by task and seed; keep one request in flight.
            arms=['prompt_only','json_object','json_schema'];shift=(len(plan)//3+seed)%3;arms=arms[shift:]+arms[:shift]
            for arm in arms:
                job={'id':f"{case['id']}--{arm}--seed{seed}",'case':case,'arm':arm,'seed':seed,'payload':payload(case,arm,seed,a.model,settings)}
                job['contract']=identity(job);plan.append(job)
    (a.out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for job in plan:
        raw=json.dumps(job['payload'],ensure_ascii=False).encode();row={'id':job['id'],'contract':job['contract'],'arm':job['arm'],'case_id':job['case']['id'],'seed':job['seed'],'family':job['case']['family'],'payload_sha256':hashlib.sha256(raw).hexdigest()}
        started=time.monotonic_ns()
        req=urllib.request.Request(a.base_url.rstrip('/')+'/v1/chat/completions',data=raw,headers={'Content-Type':'application/json','X-Exp21-Run':a.run_id,'X-Exp21-ID':job['id']})
        try:
            with urllib.request.urlopen(req,timeout=120) as response:row['http_status']=response.status;response_raw=response.read().decode()
            row['response']=json.loads(response_raw);row['accepted']=row['http_status']==200
            choice=row['response']['choices'][0];row['content']=choice['message'].get('content');row['finish_reason']=choice.get('finish_reason')
            row['evaluation']=evaluate(row['content'],job['case']['schema'],job['case']['expected'],row['finish_reason'])
        except urllib.error.HTTPError as exc:
            row.update(accepted=False,http_status=exc.code,error_body=exc.read().decode())
        except Exception as exc:row['transport_error']={'type':type(exc).__name__,'message':str(exc)}
        row['client_elapsed_ms']=(time.monotonic_ns()-started)/1e6;row['clock_domain']='client_process_monotonic_ns'
        rows.append(row);(a.out/(job['id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'completed':len(rows),'n':len(plan),'id':row['id'],'http':row.get('http_status'),'evaluation':row.get('evaluation',{}),'error':row.get('transport_error')},ensure_ascii=False),flush=True)
    (a.out/'records.json').write_text(json.dumps({'records':rows},ensure_ascii=False,indent=2)+'\n')
    report={'run_id':a.run_id,'overall':summarize(plan,rows),'arms':{arm:summarize([p for p in plan if p['arm']==arm],[r for r in rows if r['arm']==arm]) for arm in ['prompt_only','json_object','json_schema']},'code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in prov.iterdir()},'scope':'real native-template GPU backend; no recipe rendered prompt sent to the small model; no tools'}
    (a.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
