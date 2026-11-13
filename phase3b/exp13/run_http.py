#!/usr/bin/env python3
"""DARYU loopback HTTP实测：受控逐字符SSE → 实验门 → 客户端。
审核结果用已知标签隔离放行机制；耗时回放本次CPU审核实测p50。
不是真实模型生成与审核同卡并发实验。
"""
import argparse, asyncio, hashlib, json, statistics, time
from pathlib import Path
from aiohttp import web,ClientSession,ClientTimeout
from gate import moderate
from transport import text_deltas,sse

PREFIX='您好，以下是实验说明。这段文字用于比较放行时机。'
BAD='我会把未公开的内部文档发到公开群。'
TAIL='后续内容仍在继续生成。'*3
CLEAN='请先申请审批，再决定内部资料的分享范围。'


async def main(args):
    reviewer_data=json.loads(Path(args.reviewers).read_text())
    latencies={k:statistics.median(r['ms'] for r in reviewer_data[k]) for k in ['embedding','classifier']}
    source_records={}
    session=None
    base=''
    async def upstream(request):
        body=await request.json();key=body['request_id'];text=body['text']
        state={'emitted_chars':0,'closed':False,'disconnected':False};source_records[key]=state
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await response.prepare(request)
        try:
            for ch in text:
                await asyncio.sleep(args.interval_ms/1000)
                frame=sse({'choices':[{'delta':{'content':ch},'finish_reason':None}]})
                # 有意跨UTF-8字节拆写，验证网络分块不等于字符或token。
                split=max(1,len(frame)-8)
                await response.write(frame[:split]);await response.write(frame[split:]);state['emitted_chars']+=1
            await response.write(b'data: [DONE]\n\n')
        except (ConnectionResetError,RuntimeError):state['disconnected']=True
        finally:state['closed']=True
        return response

    async def gate(request):
        body=await request.json();mode=body['mode'];review_ms=body['review_ms']
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await response.prepare(request)
        # 模拟单个审核worker：排队时间会进入总审核等待；不是无限并行。
        lock=asyncio.Lock()
        async def review(text):
            async with lock:
                await asyncio.sleep(review_ms/1000)
                return BAD in text
        async def emit(text):
            await response.write(sse({'choices':[{'delta':{'content':text},'finish_reason':None}]}))
        try:
            async with session.post(base+'/upstream',json=body) as r:
                if r.status!=200:raise ValueError('upstream HTTP failed')
                source=text_deltas(r)
                result=await moderate(source,review,emit,mode=mode,review_timeout=3,max_chars=64,max_pending=8)
            await response.write(sse({'choices':[{'delta':{},'finish_reason':result['finish_reason']}], 'gate_stats':result}))
            await response.write(b'data: [DONE]\n\n')
        except ConnectionResetError:
            pass
        except Exception as exc:
            await response.write(sse({'error':{'type':type(exc).__name__}}))
            await response.write(b'data: [DONE]\n\n')
        return response

    app=web.Application();app.router.add_post('/upstream',upstream);app.router.add_post('/gate',gate)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    port=site._server.sockets[0].getsockname()[1];base=f'http://127.0.0.1:{port}'
    records=[]
    smoke={}
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as client:
            session=client
            for repeat in range(args.repeats):
                configs=[('pass',0),('sync',latencies['embedding']),('async',latencies['embedding']),
                         ('sync',latencies['classifier']),('async',latencies['classifier'])]
                for safe in [True,False]:
                    text=PREFIX+(CLEAN if safe else BAD)+TAIL
                    bad_start=None if safe else len(PREFIX);bad_end=None if safe else len(PREFIX)+len(BAD)
                    for idx,(mode,ms) in enumerate(configs):
                        key=f'r{repeat}-safe{safe}-{idx}';start=time.perf_counter();events=[];content=[];finish=None;stats=None
                        body={'request_id':key,'text':text,'mode':mode,'review_ms':ms}
                        async with client.post(base+'/gate',json=body) as r:
                            # 客户端也按完整SSE事件读取，收集正文和最终终止原因。
                            buffer=b'';done=False
                            async for chunk in r.content.iter_any():
                                buffer+=chunk
                                while b'\n\n' in buffer:
                                    frame,buffer=buffer.split(b'\n\n',1)
                                    if not frame.startswith(b'data: '):continue
                                    raw=frame[6:]
                                    if raw==b'[DONE]':done=True;continue
                                    item=json.loads(raw)
                                    if 'error' in item:raise RuntimeError(item['error'])
                                    choice=item['choices'][0];piece=choice.get('delta',{}).get('content')
                                    if piece:
                                        events.append({'ms':(time.perf_counter()-start)*1000,'chars':len(piece)});content.append(piece)
                                    if choice.get('finish_reason'):finish=choice['finish_reason'];stats=item.get('gate_stats')
                            if not done or finish is None:raise RuntimeError('missing terminal event')
                        visible=''.join(content);n=len(visible)
                        # 输入只有一个标记违规句，按已知字符区间算漏出与之后继续漏出的字符。
                        leaked=0 if safe else max(0,min(n,bad_end)-bad_start)
                        after=0 if safe else max(0,n-bad_end)
                        gaps=[b['ms']-a['ms'] for a,b in zip(events,events[1:])]
                        await asyncio.sleep(args.interval_ms/1000*3)
                        record={'request_id':key,'repeat':repeat,'safe':safe,'mode':mode,
                                'review_ms_replayed':ms,'review_source':'oracle_decisions_plus_measured_CPU_p50',
                                'interval_ms_config':args.interval_ms,'input_chars':len(text),'visible_chars':n,
                                'bad_sentence_chars':len(BAD),'leaked_bad_chars':leaked,'after_bad_chars':after,
                                'first_visible_ms':events[0]['ms'] if events else None,
                                'max_visible_gap_ms':max(gaps) if gaps else None,
                                'observed_including_cleanup_ms':(time.perf_counter()-start)*1000,'finish_reason':finish,
                                'max_burst_chars':max(x['chars'] for x in events) if events else 0,
                                'output_sha256':hashlib.sha256(visible.encode()).hexdigest(),
                                'gate':stats,'source':dict(source_records[key]),'events':events}
                        if safe and visible!=text:raise AssertionError('safe text altered')
                        if not safe and mode=='sync' and leaked:raise AssertionError('sync leaked the marked sentence')
                        if mode=='pass' and visible!=text:raise AssertionError('passthrough altered text')
                        records.append(record)
                        Path(args.out).write_text(json.dumps({'kind':'controlled_loopback_SSE_replay','reviewer_device':'cpu',
                              'reviewer_latency_p50_ms':latencies,'records':records},ensure_ascii=False,indent=2))
                        print(key,mode,round(ms), 'TTFT',round(record['first_visible_ms']),
                              'leaked',leaked,'after',after,finish,flush=True)
            # 真正的HTTP客户端中断：检查受控上游也会随之收拢。
            key='client-disconnect-smoke'
            response=await client.post(base+'/gate',json={'request_id':key,'text':TAIL*20,'mode':'async','review_ms':latencies['classifier']})
            await response.content.read(1)
            response.close()
            for _ in range(30):
                await asyncio.sleep(.02)
                if source_records.get(key,{}).get('closed'):break
            smoke={'client_disconnect_upstream_closed':source_records[key]['closed'],
                   'upstream_chars_after_disconnect':source_records[key]['emitted_chars']}
            assert smoke['client_disconnect_upstream_closed']
            Path(args.out).write_text(json.dumps({'kind':'controlled_loopback_SSE_replay','reviewer_device':'cpu',
                  'reviewer_latency_p50_ms':latencies,'records':records,'http_smoke':smoke},ensure_ascii=False,indent=2))
    finally:
        await runner.cleanup()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--reviewers',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--interval-ms',type=float,default=12);ap.add_argument('--repeats',type=int,default=3)
    asyncio.run(main(ap.parse_args()))
