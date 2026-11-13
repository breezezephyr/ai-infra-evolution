import asyncio,json
import httpx,pytest
from gateway import Gateway,make_plan


def test_native_utf8_byte_fragmentation_and_usage():
 async def run():
  g=Gateway(make_plan()['cases']);c=g.cases['gpu-normal'];a={'request_id':c['request_id'],'attempt_id':'test','raw_sse':''}
  raw=('data: '+json.dumps({'choices':[{'delta':{'content':'中文'},'finish_reason':None}]},ensure_ascii=False)+'\n\n'+'data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\n'+'data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}})+'\n\ndata: [DONE]\n\n').encode()
  class Bytes(httpx.AsyncByteStream):
   async def __aiter__(self):
    for x in raw:yield bytes([x])
  original=httpx.AsyncClient
  def client(**kw):
   return original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Bytes())))
  from unittest.mock import patch
  with patch('gateway.httpx.AsyncClient',client):items=[x async for x in g.source(c,a,None)]
  assert items==[{'kind':'content','text':'中文'},{'kind':'finish','finish':'stop'},{'kind':'usage','usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}}]
  assert a['raw_sse'].encode()==raw
 asyncio.run(run())

@pytest.mark.parametrize('usages,known',[
 ([{'prompt_tokens':3,'completion_tokens':2,'total_tokens':-5}],None),
 ([{'prompt_tokens':True,'completion_tokens':2,'total_tokens':3}],None),
 ([{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5},{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}],{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}),
])
def test_bad_or_conflicting_usage_cannot_be_published_as_completed(usages,known):
 async def run():
  g=Gateway(make_plan()['cases']);messages=[];rx=asyncio.Queue()
  await rx.put({'type':'http.request','body':b'{"case_id":"gpu-normal"}','more_body':False})
  raw='data: '+json.dumps({'choices':[{'delta':{'content':'OK'},'finish_reason':'stop'}]})+'\n\n'
  raw+=''.join('data: '+json.dumps({'choices':[],'usage':u})+'\n\n' for u in usages)+'data: [DONE]\n\n'
  original=httpx.AsyncClient
  from unittest.mock import patch
  async def send(m):messages.append(m)
  with patch('gateway.httpx.AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=raw)))):
   await g({'type':'http','path':'/generate','method':'POST'},rx.get,send)
  r=g.records[0];assert r['terminal']=='backend_error'
  assert r['attempts'][0]['usage']==r['settlements'][0]['usage']==known
  assert r['attempts'][0]['usage_frames']==usages
  assert not g.active and not g.worker_count
 asyncio.run(run())

@pytest.mark.parametrize('replacement',[b'',b'data: [DONE]\n\n',b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'])
def test_native_reject_missing_or_duplicate_finish(replacement):
 async def run():
  g=Gateway(make_plan()['cases']);c=g.cases['gpu-normal'];a={'request_id':c['request_id'],'attempt_id':'test','raw_sse':''}
  raw=b'data: {"choices":[{"delta":{"content":"x"},"finish_reason":null}]}\n\n'+replacement+b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
  if not replacement:raw=raw.rsplit(b'data: ',1)[0]
  original=httpx.AsyncClient
  from unittest.mock import patch
  with patch('gateway.httpx.AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=raw)))):
   with pytest.raises(Exception):[x async for x in g.source(c,a,None)]
 asyncio.run(run())
