"""Instrumentation for an isolated vLLM 0.8.5 V0 server, not a production plugin.

All synthetic request IDs start with exp22-. No credentials are recorded.
Scheduler records are CPU scheduling decisions, not CUDA execution traces.
"""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import threading
import time

LOCK = threading.Lock()
PATH = Path(os.environ['EXP22_AUDIT_PATH'])


def write(record):
    record['backend_monotonic_ns'] = time.monotonic_ns()
    with LOCK, PATH.open('a') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str)+'\n')


def install_hooks():
    from vllm.engine.async_llm_engine import AsyncLLMEngine
    from vllm.core.scheduler import Scheduler
    original_generate = AsyncLLMEngine.generate
    original_schedule = Scheduler.schedule

    async def generate(self, prompt, sampling_params, request_id, *args, **kwargs):
        audited = 'exp22-' in request_id
        if audited:
            engine = self.engine
            write({'event':'engine_request','request_id':request_id,
                   'settings':{k:getattr(sampling_params,k,None) for k in
                               ('temperature','top_p','top_k','seed','max_tokens','n')},
                   'effective_config':{
                       'engine':'V0 AsyncLLMEngine',
                       'max_num_seqs':engine.scheduler_config.max_num_seqs,
                       'max_num_batched_tokens':engine.scheduler_config.max_num_batched_tokens,
                       'chunked_prefill_enabled':engine.scheduler_config.chunked_prefill_enabled,
                       'enable_prefix_caching':engine.cache_config.enable_prefix_caching,
                       'enforce_eager':engine.model_config.enforce_eager,
                       'dtype':str(engine.model_config.dtype),
                   }})
        async for result in original_generate(self,prompt,sampling_params,request_id,*args,**kwargs):
            if audited and result.finished:
                ids=list(result.prompt_token_ids or [])
                write({'event':'engine_finished','request_id':request_id,
                       'prompt_token_ids':ids,
                       'prompt_ids_sha256':hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest(),
                       'metrics':dataclasses.asdict(result.metrics) if result.metrics else None,
                       'outputs':[{'text':o.text,'token_ids':list(o.token_ids),
                                   'finish_reason':o.finish_reason,'stop_reason':o.stop_reason} for o in result.outputs]})
            yield result

    def schedule(self):
        result=original_schedule(self)
        metadata, outputs, allow_async=result
        groups=[{'request_id':g.seq_group.request_id,'is_prefill':g.seq_group.is_prefill(),
                 'token_chunk_size':g.token_chunk_size} for g in outputs.scheduled_seq_groups]
        if any('exp22-' in g['request_id'] for g in groups):
            write({'event':'scheduler_plan','groups':groups,
                   'num_prefill_groups':outputs.num_prefill_groups,
                   'num_batched_tokens':outputs.num_batched_tokens,
                   'allow_async_output_proc':allow_async})
        return result

    AsyncLLMEngine.generate=generate
    Scheduler.schedule=schedule


install_hooks()


class AuditMiddleware:
    def __init__(self, app):
        self.app=app

    async def __call__(self, scope, receive, send):
        headers={k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
        row_id=headers.get('x-request-id','')
        if scope.get('type')!='http' or scope.get('path')!='/v1/chat/completions' or not row_id.startswith('exp22-'):
            return await self.app(scope,receive,send)
        messages=[];body=b''
        while True:
            message=await receive();messages.append(message)
            body+=message.get('body',b'')
            if not message.get('more_body',False):break
        write({'event':'api_ingress','id':row_id,'body_sha256':hashlib.sha256(body).hexdigest()})
        index=0
        async def replay():
            nonlocal index
            if index<len(messages):
                message=messages[index];index+=1;return message
            return await receive()
        async def traced_send(message):
            if message['type']=='http.response.start':
                write({'event':'api_response','id':row_id,'status':message['status']})
            if message['type']=='http.response.body' and not message.get('more_body',False):
                write({'event':'api_finished','id':row_id})
            await send(message)
        await self.app(scope,replay,traced_send)
