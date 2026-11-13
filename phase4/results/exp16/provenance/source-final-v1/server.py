"""Loopback-only experiment. JSON/WS over SSH is a control baseline, not a protocol race."""
import argparse
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import re
import subprocess
import time
import wave
from pathlib import Path
from aiohttp import web, WSMsgType
from engine import CancelModels, Generation, PROMPT, NEXT_PROMPT, retained_history

ROOT = Path(__file__).resolve().parent


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def create_app(models, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    app = web.Application(); admission = asyncio.Lock()
    resource = []
    def gpu():
        result = subprocess.run(['/usr/lib/wsl/lib/nvidia-smi','--query-gpu=memory.used,utilization.gpu',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
        memory, utilization = map(int, result.stdout.strip().split(','))
        return dict(monotonic_ns=time.perf_counter_ns(), memory_mib=memory, utilization_percent=utilization)
    async def monitor():
        try:
            while True:
                resource.append(await asyncio.to_thread(gpu)); await asyncio.sleep(.5)
        finally: save(output/'gpu-samples.json', resource)
    async def startup(app):
        app['monitor'] = asyncio.create_task(monitor())
        packages = {p:importlib.metadata.version(p) for p in ['torch','transformers','kokoro','aiohttp']}
        hashes = {str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [*ROOT.glob('*.py'), *ROOT.glob('*.js'), ROOT.parent/'exp14/models.py', ROOT.parent/'exp14/logic.py']}
        save(output/'environment.json', dict(models=models.metadata, packages=packages, source_sha256=hashes,
            output_rate=24000, asr_vad='not run; playback-position control', initial_gpu=gpu()))
    async def cleanup(app):
        app['monitor'].cancel(); await asyncio.gather(app['monitor'], return_exceptions=True)
    app.on_startup.append(startup); app.on_cleanup.append(cleanup)

    async def health(request):
        return web.json_response(dict(busy=admission.locked(), models=models.metadata))

    async def probe(request):
        body = await request.json(); kind = body['kind']; run = body['run_id']
        if kind not in ('llm', 'tts') or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', run):
            raise web.HTTPBadRequest()
        target = output/f'probe-{run}.json'
        if target.exists(): raise web.HTTPConflict()
        async with admission:
            g = Generation(models, 1, PROMPT, [])
            g.session_id = run
            g.start(); deadline = time.monotonic()+60
            trigger = 'llm_piece' if kind == 'llm' else 'tts_call_start'
            while not any(e['event'] == trigger for e in g.events):
                if time.monotonic() > deadline or g.finished():
                    g.cancel(); await asyncio.to_thread(g.join); raise RuntimeError('probe boundary missing')
                await asyncio.sleep(.002)
            if kind == 'tts': await asyncio.sleep(.05)
            g.event('probe_detection', kind=kind); g.cancel()
            await asyncio.to_thread(g.join)
            result = dict(run_id=run, kind=kind, state=g.state, events=sorted(g.events,key=lambda e:e['monotonic_ns']),
                          segments=g.segments, source='actual CUDA; synthetic boundary control')
            save(target, result)
            return web.json_response(result)

    async def websocket(request):
        run = request.query.get('run_id','')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', run): raise web.HTTPBadRequest()
        path = output/f'server-{run}.json'
        if path.exists(): raise web.HTTPConflict()
        ws = web.WebSocketResponse(heartbeat=20); await ws.prepare(request)
        if admission.locked():
            await ws.send_json(dict(type='error', error='busy')); await ws.close(); return ws
        async with admission:
            generations = {}; tasks = []; playback = {}; sent = {}; ack = {}; pcm_sent = {}
            finished = {}; ready_next = False; client_result = None; errors = []; policy = None
            async def send(data): await ws.send_json(data)

            async def next_if_ready():
                nonlocal ready_next
                if not ready_next and finished.get(1) and 1 in playback:
                    ready_next = True
                    g = generations[1]
                    text = retained_history(g.segments, playback[1])
                    g.event('history_committed', played=playback[1], retained_text=text,
                            generated_text=g.state['text'], policy=policy)
                    await send(dict(type='history', generation=1, played=playback[1], text=text,
                                    generated_text=g.state['text'], segments=g.segments))
                    await send(dict(type='next_ready'))

            async def stream(g):
                generation = g.generation
                try:
                    g.start()
                    while True:
                        item = g.pop(0)
                        if item:
                            if item['type'] == 'audio':
                                size = len(item['pcm'])//2
                                while sent[generation]+size-ack[generation] > 48000 and not g.stop.is_set():
                                    await asyncio.sleep(.002)
                                if g.stop.is_set(): continue
                                encoded = dict(item, pcm=base64.b64encode(item['pcm']).decode())
                                # Fence checked in this event loop immediately before the socket write.
                                await send(encoded)
                                sent[generation] += size
                                pcm_sent[generation].extend(item['pcm'])
                                g.event('audio_sent', offset=item['offset'], samples=size)
                            else: await send(item)
                        else:
                            # A producer can put the last item just before its return flag.
                            if g.finished() and (g.stop.is_set() or g.output.empty()): break
                            await asyncio.sleep(.002)
                    await asyncio.to_thread(g.join)
                    if g.state.get('llm_error') or g.state.get('tts_error'):
                        raise RuntimeError(str(g.state))
                    finished[generation] = True
                    await send(dict(type='generation_done', generation=generation, sent=sent[generation], state=g.state))
                    await send(dict(type='workers_joined', generation=generation, llm_stopped=True, tts_stopped=True))
                    await next_if_ready()
                except BaseException as exc:
                    g.cancel(); await asyncio.to_thread(g.join)
                    errors.append(repr(exc))
                    if not ws.closed: await send(dict(type='error', error=repr(exc)))

            await send(dict(type='ready', output_rate=24000, max_inflight_samples=48000))
            try:
                async for message in ws:
                    if message.type != WSMsgType.TEXT: break
                    body = json.loads(message.data); kind = body['type']
                    if kind == 'start':
                        if generations: raise ValueError('duplicate start')
                        policy = body['policy']
                        if policy not in ('full','server_only'): raise ValueError('policy')
                        sent[1] = ack[1] = 0; pcm_sent[1] = bytearray()
                        g = generations[1] = Generation(models,1,PROMPT,[])
                        g.session_id = run
                        g.event('session_start', run_id=run, policy=policy, trigger_samples=body['trigger_samples'])
                        tasks.append(asyncio.create_task(stream(g)))
                    elif kind == 'ack':
                        generation, played = body['generation'], body['played']
                        if type(played) is not int or not ack[generation] <= played <= sent[generation]:
                            raise ValueError('invalid ACK')
                        ack[generation] = played
                    elif kind == 'cancel':
                        g = generations[body['generation']]
                        g.event('client_cancel_control', played=body['played'])
                        g.cancel()
                        # Controlled late old-generation frame: not a network-loss experiment.
                        await asyncio.sleep(.03)
                        await send(dict(type='stale_probe',generation=1,segment=0,offset=sent[1],
                                        pcm=base64.b64encode(b'\x00\x20'*480).decode(),controlled=True))
                        g.event('controlled_stale_probe_sent', samples=480)
                    elif kind == 'playback_stopped':
                        generation, played = body['generation'], body['played']
                        if generation in playback or type(played) is not int or not 0 <= played <= sent[generation]:
                            raise ValueError('invalid playback terminal')
                        playback[generation] = played
                        generations[generation].event('playback_report_received', played=played)
                        await next_if_ready()
                        if generation == 2: await send(dict(type='await_client_result'))
                    elif kind == 'start_next':
                        if not ready_next or 2 in generations: raise ValueError('next before cleanup')
                        history = [{'role':'user','content':PROMPT}]
                        text = retained_history(generations[1].segments,playback[1])
                        if text: history.append({'role':'assistant','content':text})
                        sent[2] = ack[2] = 0; pcm_sent[2] = bytearray()
                        g = generations[2] = Generation(models,2,NEXT_PROMPT,history)
                        g.session_id = run
                        tasks.append(asyncio.create_task(stream(g)))
                    elif kind == 'client_result':
                        client_result = body['record']
                        if not finished.get(2) or 2 not in playback: raise ValueError('early client_result')
                        await send(dict(type='finished')); break
                    else: raise ValueError(f'unknown control {kind}')
            except BaseException as exc:
                errors.append(repr(exc))
                if not ws.closed: await send(dict(type='error',error=repr(exc)))
            finally:
                for g in generations.values():
                    if not g.finished(): g.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for generation, pcm in pcm_sent.items():
                    with wave.open(str(output/f'{run}-g{generation}-sent.wav'), 'wb') as audio:
                        audio.setparams((1,2,24000,0,'NONE','not compressed')); audio.writeframes(pcm)
                save(path,dict(run_id=run,policy=policy,errors=errors,client_result=client_result,
                    playback=playback,sent=sent,ack=ack,generations={str(k):dict(state=g.state,
                        segments=g.segments,sent_pcm_sha256=hashlib.sha256(pcm_sent[k]).hexdigest(),
                        events=sorted(g.events,key=lambda e:e['monotonic_ns'])) for k,g in generations.items()}))
                await ws.close()
        return ws

    app.router.add_get('/health',health); app.router.add_post('/probe',probe)
    app.router.add_get('/ws',websocket)
    for file in ['index.html','client.js','worklet.js']:
        async def static(request, name=file): return web.FileResponse(ROOT/name)
        app.router.add_get('/' if file=='index.html' else '/'+file,static)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=18149)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    models = CancelModels()
    web.run_app(create_app(models,args.output),host='127.0.0.1',port=args.port)
