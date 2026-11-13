import asyncio
import json
from pathlib import Path

from gateway import Gateway
from plan import make_plan
from test_gateway import request, Fixture


def test_retry_waits_for_backend_release():
 async def run():
  released=asyncio.Event();entered=asyncio.Event();second=[]
  class Source(Fixture):
   async def __call__(self,c,a,fault):
    if fault=='pre_timeout':await asyncio.sleep(1)
    else:
     second.append(released.is_set())
     async for x in super().__call__(c,a,fault):yield x
  p=make_plan();g=Gateway(p,encoder=lambda m:[1],native_source=Source())
  async def barrier(c,a):
   entered.set();await released.wait()
  g.base.before_retry=barrier
  c=next(c for c in p['cases'] if c['case_id']=='retry-before-content')
  job=asyncio.create_task(request(g,c))
  await asyncio.sleep(.2)
  assert entered.is_set() and not second
  released.set();r,_=await job
  assert second==[True] and r['terminal']=='completed'
 asyncio.run(run())


def test_native_barrier_requires_terminal_then_empty_tracker(tmp_path):
 async def run():
  from gateway import wait_native_release
  path=tmp_path/'backend.jsonl';aid='req/a1'
  def append(**kw):
   with path.open('a') as f:f.write(json.dumps({'attempt_id':aid,**kw})+'\n')
  append(event='state_after',backend_monotonic_ns=1,snapshot_complete=True,pending_or_unfinished=False,tracker={'active_stream':False,'new_pending':False,'abort_pending':False})
  task=asyncio.create_task(wait_native_release(path,aid,timeout=.5))
  await asyncio.sleep(.02);assert not task.done()
  append(event='abort_returned',backend_monotonic_ns=2,error=None)
  append(event='state_after',backend_monotonic_ns=3,snapshot_complete=True,pending_or_unfinished=True,tracker={'abort_pending':True})
  await asyncio.sleep(.02);assert not task.done()
  append(event='state_after',backend_monotonic_ns=4,snapshot_complete=True,pending_or_unfinished=False,engine_pending_or_unfinished=False,tracker={'active_stream':False,'new_pending':False,'abort_pending':False},error=None)
  await task
 asyncio.run(run())
