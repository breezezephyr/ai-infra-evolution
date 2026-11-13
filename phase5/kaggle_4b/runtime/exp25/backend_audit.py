from common import alias, model_path, model_identity as portable_identity, backend_command, backend_env, exec_frozen, install_signals, identity_valid
"""Transparent ASGI ingress/response evidence for this lab, not an engine hook."""
import os,json,time,hashlib,pathlib
class AuditMiddleware:
 def __init__(self,app):self.app=app
 async def __call__(self,scope,receive,send):
  if scope['type']!='http' or scope.get('path')!='/v1/chat/completions':return await self.app(scope,receive,send)
  headers={k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
  request=bytearray();response=bytearray();status=None;t=time.monotonic_ns();first=None
  async def recv():
   event=await receive()
   if event['type']=='http.request':request.extend(event.get('body',b''))
   return event
  async def sent(event):
   nonlocal status,first
   if event['type']=='http.response.start':status=event['status']
   if event['type']=='http.response.body':
    data=event.get('body',b'');response.extend(data)
    if data and first is None:first=time.monotonic_ns()
   await send(event)
  error=None
  try:await self.app(scope,recv,sent)
  except BaseException as e:error=type(e).__name__;raise
  finally:
   row={'component':'backend-http','clock_domain':f'kaggle-backend-{os.getpid()}',
    'request_id':headers.get('x-exp25-request-id'),'attempt_id':headers.get('x-exp25-attempt-id'),
    'status':status,'request_sha256':hashlib.sha256(request).hexdigest(),'body':request.decode(errors='replace'),
    'response_sha256':hashlib.sha256(response).hexdigest(),'sse':response.decode(errors='replace'),
    'started_ns':t,'first_body_ns':first,'ended_ns':time.monotonic_ns(),'error':error}
   with pathlib.Path(os.environ['EXP25_AUDIT_PATH']).open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
