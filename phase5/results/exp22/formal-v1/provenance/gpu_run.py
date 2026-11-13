"""Actual HTTP gateway + frozen, closed-loop synthetic workload for exp22."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import random
import threading
import time
import urllib.error
import urllib.request
from measure import Admission, Overloaded


def fixtures():
    records='\n'.join(f'班次{i:02d}：始发站青山，终点站河湾，计划发车08:{i%60:02d}，状态正常。' for i in range(1,31))
    return [
        {'task':'short-interactive-a','kind':'interactive','input':'用一句话解释公交专用道的作用。','max_tokens':32},
        {'task':'short-interactive-b','kind':'interactive','input':'只返回 17 加 26 的结果，不要解释。','max_tokens':32},
        {'task':'long-interactive-a','kind':'interactive','input':records+'\n只回答这里共有几条班次记录。','max_tokens':32},
        {'task':'long-interactive-b','kind':'interactive','input':records+'\n只回答班次07的计划发车时间。','max_tokens':32},
        {'task':'short-batch-a','kind':'batch','input':'分条说明公交调度员安排车辆时需要考虑的因素。','max_tokens':96},
        {'task':'short-batch-b','kind':'batch','input':'写一段向新乘客介绍公交换乘方法的中文说明。','max_tokens':96},
        {'task':'long-batch-a','kind':'batch','input':records+'\n根据这些记录写一段班次运行总结。','max_tokens':96},
        {'task':'long-batch-b','kind':'batch','input':records+'\n分条解释乘客查阅这些班次时应该关注什么。','max_tokens':96},
    ]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backend',default='http://127.0.0.1:18022')
    parser.add_argument('--model',default='exp22-qwen3-0.6b')
    parser.add_argument('--out',required=True)
    parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args()
    root=Path(args.out);root.mkdir(parents=True,exist_ok=False)
    run_id='exp22-'+root.name
    gate=Admission(active_limit=2,waiting_limit=2)
    log_lock=threading.Lock()
    def log(row):
        with log_lock, (root/'gateway.jsonl').open('a') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_POST(self):
            arrived=time.monotonic_ns()
            body=self.rfile.read(int(self.headers['Content-Length']))
            row_id=self.headers['X-Request-Id'];ticket=None
            row={'id':row_id,'clock_domain':'local_monotonic','arrival_ns':arrived,
                 'body_sha256':hashlib.sha256(body).hexdigest(),'mode':self.path.strip('/')}
            try:
                if self.path=='/bounded':ticket=gate.enter()
                elif self.path!='/direct':raise ValueError('bad route')
                dispatched=time.monotonic_ns()
                row.update(dispatched_ns=dispatched,gateway_wait_ms=(dispatched-arrived)/1e6)
                request=urllib.request.Request(args.backend+'/v1/chat/completions',data=body,
                    headers={'Content-Type':'application/json','X-Request-Id':row_id})
                try:
                    with urllib.request.urlopen(request,timeout=120) as response:
                        status=response.status;data=response.read()
                except urllib.error.HTTPError as error:
                    status=error.code;data=error.read()
            except Overloaded:
                status=429;data=b'{"error":"admission queue full"}'
            except Exception as error:
                status=502;data=json.dumps({'error':type(error).__name__}).encode()
            finally:
                if ticket:ticket.release()
            row.update(status=status,finished_ns=time.monotonic_ns())
            log(row)
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    gateway=f'http://127.0.0.1:{server.server_port}'
    rng=random.Random(20261026)
    configs=[(mode,c) for mode in ('direct','bounded') for c in (1,2,4)]
    batches=[]
    for repeat in range(3 if not args.preflight else 1):
        order=configs.copy();rng.shuffle(order)
        if repeat==0:order.remove(('direct',1));order.insert(0,('direct',1))
        if args.preflight:order=[('direct',1),('direct',4)]
        for mode,c in order:
            tasks=fixtures();rng.shuffle(tasks)
            if args.preflight:tasks=[tasks[0],next(t for t in fixtures() if t['task']=='long-batch-a')]
            batches.append({'repeat':repeat,'mode':mode,'concurrency':c,'tasks':tasks})
    plan={'run_id':run_id,'preflight':args.preflight,'model':args.model,'backend':args.backend,
          'admission':{'active':2,'waiting':2,'queue_order':'unspecified'},'batches':batches,
          'sampling':{'temperature':0,'top_p':1,'top_k':-1,'seed':17,'chat_template_kwargs':{'enable_thinking':False}},
          'workload':'closed loop thread pool; eight offered tasks per batch; driver wait and HTTP roundtrip separate'}
    (root/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    def call(task,identity,mode,submitted):
        started=time.monotonic_ns()
        payload={'model':args.model,'messages':[{'role':'user','content':task['input']}],
                 **plan['sampling'],'max_tokens':task['max_tokens'],'stream':False}
        body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        request=urllib.request.Request(gateway+'/'+mode,data=body,
            headers={'Content-Type':'application/json','X-Request-Id':identity})
        status=None;data=b'';error=None
        try:
            with urllib.request.urlopen(request,timeout=150) as response:
                status=response.status;data=response.read()
        except urllib.error.HTTPError as exc:
            status=exc.code;data=exc.read()
        except Exception as exc:error=type(exc).__name__
        return {'id':identity,'task':task['task'],'kind':task['kind'],'status':status,'error':error,
                'body_sha256':hashlib.sha256(body).hexdigest(),'submitted_ns':submitted,'started_ns':started,
                'finished_ns':time.monotonic_ns(),'response':json.loads(data) if data else None}
    try:
        for number,batch in enumerate(batches):
            start=time.monotonic_ns()
            with ThreadPoolExecutor(max_workers=batch['concurrency']) as pool:
                futures=[]
                for index,task in enumerate(batch['tasks']):
                    identity=f'{run_id}-b{number:02d}-i{index}'
                    futures.append(pool.submit(call,task,identity,batch['mode'],time.monotonic_ns()))
                for future in as_completed(futures):
                    row=future.result();row.update(batch=number,repeat=batch['repeat'],mode=batch['mode'],concurrency=batch['concurrency'])
                    rows.append(row)
            batch['elapsed_ms']=(time.monotonic_ns()-start)/1e6
            (root/'records.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'batch':number,'mode':batch['mode'],'concurrency':batch['concurrency'],
                              'requests':len(batch['tasks']),'elapsed_ms':round(batch['elapsed_ms'],1)},ensure_ascii=False),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
    (root/'batch-times.json').write_text(json.dumps(batches,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
