#!/usr/bin/env python3
"""同卡真实GPU生成 + 真实逐句审核，loopback HTTP/SSE。
Qwen3-0.6B生成，另一个0.6B分类，Embedding-0.6B作嵌入审核；无oracle/no sleep回放。
"""
import argparse, asyncio, gc, hashlib, json, os, threading, time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
from transformers import AutoModel,AutoModelForCausalLM,AutoTokenizer,TextIteratorStreamer,StoppingCriteria,StoppingCriteriaList
from aiohttp import web,ClientSession,ClientTimeout
from gate import moderate
from async_threads import joined_thread_call
from transport import text_deltas,sse
from run_http import PREFIX,BAD,TAIL,CLEAN

class StopEvent(StoppingCriteria):
    def __init__(self,event):self.event=event
    def __call__(self,input_ids,scores,**kwargs):return self.event.is_set()

class CountStreamer(TextIteratorStreamer):
    def __init__(self,tokenizer,state):
        super().__init__(tokenizer,skip_prompt=True,skip_special_tokens=True,timeout=20)
        self.state=state
    def put(self,value):
        prompt=self.next_tokens_are_prompt
        super().put(value)
        if not prompt:self.state['generated_new_tokens_including_eos']+=value.numel()
    def on_finalized_text(self,text,stream_end=False):
        self.state['generated_text']+=text
        super().on_finalized_text(text,stream_end)

def pop(streamer):
    try:return next(streamer)
    except StopIteration:return None

async def main(args):
    if not torch.cuda.is_available():raise RuntimeError('CUDA required')
    torch.set_num_threads(4)
    data=json.loads((Path(__file__).parent/'cases.json').read_text())
    dt=torch.bfloat16;directory='/opt/models/Qwen3-0.6B'
    gen_tok=AutoTokenizer.from_pretrained(directory,local_files_only=True)
    generator=AutoModelForCausalLM.from_pretrained(directory,local_files_only=True,torch_dtype=dt).to('cuda').eval()
    review_tok=AutoTokenizer.from_pretrained(directory,local_files_only=True)
    classifier=AutoModelForCausalLM.from_pretrained(directory,local_files_only=True,torch_dtype=dt).to('cuda').eval()
    emb_dir='/opt/models/Qwen3-Embedding-0.6B'
    emb_tok=AutoTokenizer.from_pretrained(emb_dir,local_files_only=True)
    embedder=AutoModel.from_pretrained(emb_dir,local_files_only=True,torch_dtype=dt).to('cuda').eval()
    def embed(text):
        batch=emb_tok([text],return_tensors='pt',padding=True,truncation=True,max_length=512).to('cuda')
        with torch.inference_mode():
            hidden=embedder(**batch).last_hidden_state
            v=hidden[torch.arange(hidden.shape[0],device='cuda'),batch['attention_mask'].sum(1)-1]
            return torch.nn.functional.normalize(v.float(),p=2,dim=1)[0]
    refs=torch.stack([embed(x) for x in data['references']]);torch.cuda.synchronize()
    def review_impl(text,kind,trace):
        start=time.perf_counter()
        if kind=='embedding':
            vector=embed(text);score=float((refs@vector).max().clamp(-1,1));blocked=score>=.8
            decision={'score':score,'blocked':blocked}
        else:
            prompt=review_tok.apply_chat_template([{'role':'system','content':'你是句子分类器。规则：'+data['policy']+' 仅回答 BLOCK 或 ALLOW，不要解释。'},
                          {'role':'user','content':text}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
            batch=review_tok(prompt,return_tensors='pt').to('cuda')
            with torch.inference_mode():
                out=classifier.generate(**batch,max_new_tokens=6,do_sample=False,temperature=1.0,top_p=1.0,top_k=0,pad_token_id=review_tok.eos_token_id)
            answer=review_tok.decode(out[0,batch['input_ids'].shape[1]:],skip_special_tokens=True).strip()
            if answer not in ('ALLOW','BLOCK'):raise ValueError('invalid classification')
            blocked=answer=='BLOCK';decision={'answer':answer,'blocked':blocked}
        torch.cuda.synchronize();decision.update(text=text,ms=(time.perf_counter()-start)*1000)
        trace.append(decision);return blocked

    source_records={};records=[];base='';session=None
    async def upstream(request):
        body=await request.json();key=body['request_id'];text=body['text']
        state={'generated_new_tokens_including_eos':0,'generated_text':'','closed':False,'client_disconnected':False,'thread_stopped':False,'error':None,'generation_finish_reason':None,'cancel_signal_set':False}
        source_records[key]=state;stop=threading.Event();streamer=CountStreamer(gen_tok,state)
        prompt=gen_tok.apply_chat_template([{'role':'system','content':'你是复制器。请逐字复制用户提供的正文，不添加解释、前缀、引号或其他文字。'},
                        {'role':'user','content':text}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        batch=gen_tok(prompt,return_tensors='pt').to('cuda')
        def generate():
            try:
                with torch.inference_mode():
                    outputs=generator.generate(**batch,max_new_tokens=192,do_sample=False,temperature=1.0,top_p=1.0,top_k=0,
                                       pad_token_id=gen_tok.eos_token_id,streamer=streamer,stopping_criteria=StoppingCriteriaList([StopEvent(stop)]))
                    new=outputs[0,batch['input_ids'].shape[1]:]
                    last=int(new[-1]) if len(new) else None
                    eos=gen_tok.eos_token_id
                    state['generation_finish_reason']='stop' if last==eos else ('length' if len(new)>=192 else 'cancelled' if stop.is_set() else 'unknown')
            except Exception as exc:
                state['error']=type(exc).__name__;streamer.end()
        thread=threading.Thread(target=generate,daemon=True)
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await response.prepare(request)
        thread.start();exhausted=False
        try:
            while True:
                piece=await asyncio.to_thread(pop,streamer)
                if piece is None:exhausted=True;break
                if piece:await response.write(sse({'choices':[{'delta':{'content':piece},'finish_reason':None}]}))
            await asyncio.to_thread(thread.join,10)
            if thread.is_alive():raise RuntimeError('generator did not finish')
            if state['error']:raise RuntimeError(state['error'])
            await response.write(sse({'choices':[{'delta':{},'finish_reason':state['generation_finish_reason']}]}))
            await response.write(b'data: [DONE]\n\n')
        except (ConnectionResetError,RuntimeError):
            state['client_disconnected']=True;stop.set();state['cancel_signal_set']=True
        finally:
            if thread.is_alive() and not exhausted:stop.set();state['cancel_signal_set']=True
            await asyncio.to_thread(thread.join,10)
            state['thread_stopped']=not thread.is_alive();state['closed']=True
        return response

    async def gate(request):
        body=await request.json();mode=body['mode'];kind=body['reviewer'];trace=[]
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await response.prepare(request)
        lock=asyncio.Lock()
        async def review(text):
            async with lock:return await joined_thread_call(review_impl,text,kind,trace)
        async def emit(text):await response.write(sse({'choices':[{'delta':{'content':text},'finish_reason':None}]}))
        try:
            async with session.post(base+'/upstream',json=body) as r:
                finish=[]
                result=await moderate(text_deltas(r,on_finish=finish.append),review,emit,mode=mode,review_timeout=10,max_chars=64,max_pending=8)
                if result['finish_reason']=='stop' and finish:result['finish_reason']=finish[-1]
            await response.write(sse({'choices':[{'delta':{},'finish_reason':result['finish_reason']}], 'gate_stats':result,'review_trace':trace}))
            await response.write(b'data: [DONE]\n\n')
        except ConnectionResetError:pass
        except Exception as exc:
            await response.write(sse({'error':{'type':type(exc).__name__}}));await response.write(b'data: [DONE]\n\n')
        return response

    app=web.Application();app.router.add_post('/upstream',upstream);app.router.add_post('/gate',gate)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    base=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    config={'kind':'live_GPU_generation_and_actual_review_same_card','device':torch.cuda.get_device_name(),
            'dtype':'bfloat16','generator':'Qwen3-0.6B','reviewers':['Qwen3-Embedding-0.6B','Qwen3-0.6B'],
            'max_new_tokens':192,'embedding_threshold':.8,'records':records}
    # 未计时热身，把加载/初始kernel开销放在请求性能统计之外。
    warm=gen_tok('Hello',return_tensors='pt').to('cuda')
    with torch.inference_mode():generator.generate(**warm,max_new_tokens=2,do_sample=False,temperature=1.0,top_p=1.0,top_k=0,pad_token_id=gen_tok.eos_token_id)
    torch.cuda.synchronize()
    try:
        async with ClientSession(timeout=ClientTimeout(total=90)) as client:
            session=client
            for repeat in range(args.repeats):
                for safe in [True,False]:
                    text=PREFIX+(CLEAN if safe else BAD)+TAIL
                    configs=[('pass','none'),('sync','embedding'),('async','embedding'),('sync','classifier'),('async','classifier')]
                    for mode,reviewer in configs:
                        key=f'live-{repeat}-{safe}-{mode}-{reviewer}';start=time.perf_counter();events=[];content=[];stats=None;trace=None;finish=None
                        async with client.post(base+'/gate',json={'request_id':key,'mode':mode,'reviewer':reviewer,'text':text}) as r:
                            buffer=b'';done=False
                            async for chunk in r.content.iter_any():
                                buffer+=chunk
                                while b'\n\n' in buffer:
                                    frame,buffer=buffer.split(b'\n\n',1)
                                    if not frame.startswith(b'data: '):continue
                                    if frame[6:]==b'[DONE]':done=True;continue
                                    item=json.loads(frame[6:])
                                    if 'error' in item:raise RuntimeError(item['error'])
                                    ch=item['choices'][0];piece=ch.get('delta',{}).get('content')
                                    if piece:content.append(piece);events.append({'ms':(time.perf_counter()-start)*1000,'chars':len(piece)})
                                    if ch.get('finish_reason'):finish=ch['finish_reason'];stats=item.get('gate_stats');trace=item.get('review_trace')
                            terminal_ms=(time.perf_counter()-start)*1000
                            if not done or finish is None:raise RuntimeError('missing terminal event')
                        for _ in range(600):
                            if source_records[key]['closed']:break
                            await asyncio.sleep(.02)
                        source=dict(source_records[key]);visible=''.join(content)
                        if not source['thread_stopped']:raise RuntimeError('generator thread did not stop')
                        if not source['generated_text'].startswith(visible):raise AssertionError('visible text not prefix of actual generated text')
                        pos=source['generated_text'].find(BAD)
                        known_span=pos>=0
                        blocked_span_matches_marked=(known_span and finish=='content_filter' and stats['blocked_start'] is not None and stats['blocked_start']<=pos and stats['blocked_end']>=pos+len(BAD))
                        leak=max(0,min(len(visible),pos+len(BAD))-pos) if known_span else None
                        after=max(0,len(visible)-pos-len(BAD)) if known_span else None
                        gaps=[b['ms']-a['ms'] for a,b in zip(events,events[1:])]
                        row={'request_id':key,'repeat':repeat,'safe_input':safe,'mode':mode,'reviewer':reviewer,
                             'first_visible_ms':events[0]['ms'] if events else None,'max_visible_gap_ms':max(gaps) if gaps else None,
                             'client_terminal_ms':terminal_ms,'visible_chars':len(visible),'visible_text':visible,
                             'marked_sentence_present_in_generated':known_span,'blocked_span_matches_marked':blocked_span_matches_marked,'leaked_marked_chars':leak,'after_marked_chars':after,
                             'finish_reason':finish,'gate':stats,'review_trace':trace,'source':source,
                             'copy_exact_for_observed_prefix':text.startswith(source['generated_text']) or source['generated_text']==text,
                             'events':events,'max_memory_allocated_bytes':torch.cuda.max_memory_allocated()}
                        records.append(row);Path(args.out).write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
                        print(key,'first',round(row['first_visible_ms']) if row['first_visible_ms'] else None,
                              'visible',len(visible),'leak',leak,'after',after,finish,'gen_tok',source['generated_new_tokens_including_eos'],flush=True)
    finally:
        await runner.cleanup()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--repeats',type=int,default=3)
    asyncio.run(main(ap.parse_args()))
