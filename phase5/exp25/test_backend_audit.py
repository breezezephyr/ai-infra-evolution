"""Catch swapped/missing raw ingress or response evidence without any GPU."""
import asyncio,json,hashlib
import backend_audit


def test_raw_http_stream_and_attempt_header_are_recorded_without_changing_payload(tmp_path,monkeypatch):
 monkeypatch.setenv('EXP25_AUDIT_PATH',str(tmp_path/'backend.jsonl'))
 sent=[]
 async def app(scope,receive,send):
  assert (await receive())['body']==b'{"stream":true}'
  await send({'type':'http.response.start','status':200,'headers':[]})
  await send({'type':'http.response.body','body':b'data: hello\n\n','more_body':True})
  await send({'type':'http.response.body','body':b'data: [DONE]\n\n','more_body':False})
 async def receive():return {'type':'http.request','body':b'{"stream":true}','more_body':False}
 async def send(x):sent.append(x)
 scope={'type':'http','path':'/v1/chat/completions','headers':[(b'x-exp25-request-id',b'r1'),(b'x-exp25-attempt-id',b'a1')]}
 asyncio.run(backend_audit.AuditMiddleware(app)(scope,receive,send))
 row=json.loads((tmp_path/'backend.jsonl').read_text())
 assert row['request_id']=='r1' and row['attempt_id']=='a1' and row['status']==200
 assert row['body']=='{"stream":true}'
 assert row['response_sha256']==hashlib.sha256(b'data: hello\n\ndata: [DONE]\n\n').hexdigest()
 assert row['sse']==''.join(x.get('body',b'').decode() for x in sent)
 assert row['started_ns']<=row['first_body_ns']<=row['ended_ns']
