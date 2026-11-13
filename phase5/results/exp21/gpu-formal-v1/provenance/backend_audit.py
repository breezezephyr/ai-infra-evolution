"""ASGI request evidence for an isolated exp21 model server, no credentials."""
import hashlib
import json
import os
from pathlib import Path
import time

class AuditMiddleware:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        headers={k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
        run=headers.get('x-exp21-run');row_id=headers.get('x-exp21-id')
        if scope.get('type')!='http' or scope.get('path')!='/v1/chat/completions' or not run or not row_id:
            return await self.app(scope,receive,send)
        messages=[];body=b''
        while True:
            message=await receive();messages.append(message)
            if message['type']=='http.disconnect':break
            body+=message.get('body',b'')
            if not message.get('more_body',False):break
        payload=json.loads(body)
        record={'component':'model_api_ingress','event':'request_received','run':run,'id':row_id,
                'monotonic_ns':time.monotonic_ns(),'clock_domain':'backend_process',
                'body_sha256':hashlib.sha256(body).hexdigest(),
                'settings':{k:payload[k] for k in ['model','response_format','structured_outputs','guided_json','seed','temperature','top_p','max_tokens','chat_template_kwargs'] if k in payload}}
        log=Path(os.environ['EXP21_AUDIT_PATH'])
        def write(value):
            with log.open('a') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')
        write(record)
        index=0
        async def replay():
            nonlocal index
            if index<len(messages):result=messages[index];index+=1;return result
            return await receive()
        async def traced_send(message):
            if message['type']=='http.response.start':write({'component':'model_api_ingress','event':'response_started','id':row_id,'run':run,'status':message['status']})
            await send(message)
        await self.app(scope,replay,traced_send)
