"""Synthetic cancellation boundaries on real CUDA models; no microphone claim."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def run(url, output, repeat):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    records = []
    for i in range(repeat):
        for kind in ('llm','tts'):
            run_id = f'{output.name}-{kind}-{i}'
            body = json.dumps(dict(kind=kind, run_id=run_id)).encode()
            req = Request(url+'/probe', body, {'Content-Type':'application/json'})
            with urlopen(req, timeout=120) as response: data = json.load(response)
            (output/f'{run_id}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            state = data['state']; events = data['events']
            stop = next(e['monotonic_ns'] for e in events if e['event']=='stop_signal_set')
            joined = next(e['monotonic_ns'] for e in events if e['event']=='workers_joined')
            record = dict(run_id=run_id,kind=kind,stop_to_join_ms=(joined-stop)/1e6,
                llm_finish=state['llm'].get('finish_reason'),tokens=state['llm'].get('generated_tokens'),
                discarded_samples=state['discarded_after_stop_samples'])
            records.append(record); print(json.dumps(record),flush=True)
    (output/'records.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:18149')
    p.add_argument('--output',required=True);p.add_argument('--repeat',type=int,default=3)
    args=p.parse_args();run(args.url,args.output,args.repeat)
