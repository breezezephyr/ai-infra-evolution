"""CPU replay of six captured backend SSE bodies through the fixed gateway.
No GPU calls, engine cancellation, original timing or original scenario replay.
"""
import asyncio,json,pathlib,sys,hashlib
from unittest.mock import patch
import httpx
from gateway import Gateway,make_plan
D=pathlib.Path(__file__).resolve().parent;R=D.parent/'results/exp26';F=R/'formal-v1'
async def run():
 rows=[json.loads(x) for x in (F/'backend.jsonl').read_text().splitlines() if '"http_finished"' in x]
 report=[]
 for i,b in enumerate(rows):
  c=next(c for c in make_plan()['cases'] if c['case_id']=='gpu-normal');c['request_id']='replay-'+str(i)
  g=Gateway([c]);rx=asyncio.Queue();await rx.put({'type':'http.request','body':b'{"case_id":"gpu-normal"}','more_body':False})
  original=httpx.AsyncClient
  async def send(message):pass
  with patch('gateway.httpx.AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b['sse'].encode())))):
   await g({'type':'http','path':'/generate','method':'POST'},rx.get,send)
  r=g.records[0];a=r['attempts'][0];complete='data: [DONE]' in b['sse']
  assert r['terminal']==('completed' if complete else 'backend_error')
  assert a['worker_joined'] and g.worker_count==0 and not g.active
  report.append({'captured_attempt_id':b['attempt_id'],'replay_terminal':r['terminal'],'usage':a['usage'],'worker_joined':True})
 assert len(report)==6 and sum(x['usage']['total_tokens'] for x in report if x['usage'])==248
 out={'scope':__doc__.strip(),'source_sha256':{n:hashlib.sha256((D/n).read_bytes()).hexdigest() for n in ['gateway.py','replay_native.py']},'cases':report,'accepted':True}
 (R/'native-cpu-replay.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'replays':6,'known_usage_tokens':248,'unknown':4,'new_gpu_calls':0}))
if __name__=='__main__':asyncio.run(run())
