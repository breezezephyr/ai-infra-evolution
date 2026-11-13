"""Native network boundary fixtures protect SSE termination and raw body correlation."""
import asyncio,hashlib,json,pytest,httpx
from gateway import HTTPBackend,ProtocolError
import gateway

RAW=(b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n'
     b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
     b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}}\n\n'
     b'data: [DONE]\n\n')


def test_stream_parser_preserves_usage_and_exact_bytes_sent_to_backend(monkeypatch):
 original=httpx.AsyncClient;seen=[]
 def handle(request):
  seen.append(request)
  return httpx.Response(200,content=RAW)
 monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
 body={'z':'中文','a':1}
 result=asyncio.run(HTTPBackend('http://fixture').generate(body,'r1','a1',lambda *a,**k:None))
 assert result.content=='OK' and result.finish=='stop' and result.usage['total_tokens']==9
 assert result.raw_sse.encode()==RAW
 assert seen[0].content==b'{"a":1,"z":"\xe4\xb8\xad\xe6\x96\x87"}'
 assert seen[0].headers['x-exp25-attempt-id']=='a1'


@pytest.mark.parametrize('raw',[RAW.replace(b'data: [DONE]\n\n',b''),RAW+b'data: [DONE]\n\n',RAW+b'data: {"choices":[]}\n\n'])
def test_missing_duplicate_or_late_terminal_is_protocol_error(monkeypatch,raw):
 original=httpx.AsyncClient
 monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=raw)),**kwargs))
 with pytest.raises(ProtocolError):asyncio.run(HTTPBackend('http://fixture').generate({},'r','a',lambda *a,**k:None))


@pytest.mark.parametrize('fault',['length_then_stop','content_after_finish'])
def test_conflicting_or_post_finish_backend_data_never_becomes_complete(monkeypatch,fault):
 original=httpx.AsyncClient
 if fault=='length_then_stop':
  bad=RAW.replace(b'"finish_reason":"stop"',b'"finish_reason":"length"').replace(b'data: [DONE]',b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]')
 else:
  bad=RAW.replace(b'data: [DONE]',b'data: {"choices":[{"delta":{"content":"LATE"},"finish_reason":null}]}\n\ndata: [DONE]')
 monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=bad)),**kwargs))
 with pytest.raises(ProtocolError):asyncio.run(HTTPBackend('http://fixture').generate({},'r','a',lambda *a,**k:None))
