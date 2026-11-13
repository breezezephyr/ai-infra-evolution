"""Loopback-only exp14 server. No production gateway or service configuration changes."""
import argparse
import asyncio
import hashlib
import json
import re
import threading
import time
import wave
from pathlib import Path
from aiohttp import web, WSMsgType
from logic import Endpoint
from pipeline import generate_reply
from protocol import unpack_audio, pack_audio, SequenceGuard, PCMWindows


def create_app(models, output):
    app=web.Application()
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    admission=asyncio.Lock()

    async def ws_handler(request):
        ws=web.WebSocketResponse(max_msg_size=10000,heartbeat=20)
        await ws.prepare(request)
        if admission.locked():
            await ws.send_json({'type':'terminal','finish_reason':'busy'})
            await ws.close();return ws
        async with admission:
            state={};events=[];received=bytearray();sent_pcm=bytearray()
            stop=threading.Event();reader=processing=completion=None
            input_done=asyncio.Event();endpoint_ready=asyncio.Event()
            acked=0;sent_samples=0;seq=0;endpoint_pcm=None
            session='invalid';turn=1;generation=1;input_complete=False
            def event(name,**fields):
                events.append({'event':name,'component':name.split('_')[0],
                    'clock_domain':'server_monotonic','monotonic_ns':time.perf_counter_ns(),
                    'session_id':session,'turn_id':turn,'generation_id':generation,**fields})
            reason='error'
            try:
                body=await ws.receive_json(timeout=10)
                session=body.get('session_id','');turn=body.get('turn_id');generation=body.get('generation_id')
                mode=body.get('mode')
                if (body.get('type')!='start' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',session)
                    or type(turn) is not int or type(generation) is not int
                    or not 0<=turn<2**32 or not 0<=generation<2**32 or mode not in ('A','B','C')):
                    raise ValueError('invalid start control')
                state.update(mode=mode,playback=body.get('playback','capture_only'))
                guard=SequenceGuard(turn,generation,16000*15)
                windows=PCMWindows(512);window_end=0
                endpoint=Endpoint(500 if mode=='A' else 200)
                models.vad.reset_states()
                event('turn_started',mode=mode)
                await ws.send_json({'type':'ready','input_rate':16000,'output_rate':24000,
                    'format':'pcm16le','models':models.metadata,'max_output_buffer_samples':48000})

                async def emit(pcm):
                    nonlocal sent_samples,seq
                    if sent_samples+len(pcm)//2>24000*30:
                        raise ValueError('output exceeds 30 seconds')
                    while sent_samples+len(pcm)//2-acked>48000:
                        if stop.is_set():raise ConnectionResetError('receiver stopped')
                        await asyncio.sleep(.005)
                    await ws.send_bytes(pack_audio(turn,generation,seq,sent_samples,pcm))
                    sent_samples+=len(pcm)//2;seq+=1;sent_pcm.extend(pcm)

                async def read_input():
                    nonlocal acked,window_end,endpoint_pcm,input_complete
                    try:
                        async for msg in ws:
                            if msg.type==WSMsgType.BINARY:
                                if input_done.is_set():raise ValueError('audio after input_end')
                                frame=unpack_audio(msg.data)
                                if not guard.accept(frame):continue
                                received.extend(frame.pcm)
                                event('input_frame_received',sample_offset=frame.sample_offset,samples=len(frame.pcm)//2)
                                for window in windows.feed(frame.pcm):
                                    window_end+=512
                                    if not endpoint.triggered:
                                        probability=models.speech_probability(window)
                                        if endpoint.feed(probability,window_end):
                                            endpoint_pcm=bytes(received[:window_end*2])
                                            event('endpoint_confirmed',sample_offset=window_end,
                                                  last_speech_sample=endpoint.last_speech_sample)
                                            endpoint_ready.set()
                            elif msg.type==WSMsgType.TEXT:
                                message=json.loads(msg.data)
                                if message.get('type')=='input_end':
                                    if input_done.is_set():raise ValueError('duplicate input_end')
                                    windows.finish();input_complete=True;input_done.set()
                                    event('input_complete',samples=len(received)//2)
                                    if not endpoint.triggered:raise ValueError('no speech endpoint')
                                elif message.get('type')=='ack':
                                    value=message.get('samples')
                                    if type(value) is not int or not acked<=value<=sent_samples:
                                        raise ValueError('invalid playback acknowledgement')
                                    acked=value
                                elif message.get('type')=='cancel':
                                    stop.set();event('cancel_requested');raise ConnectionResetError('client cancel')
                                else:raise ValueError('unknown control')
                            elif msg.type in (WSMsgType.ERROR,WSMsgType.CLOSE,WSMsgType.CLOSED):
                                break
                        raise ConnectionResetError('client disconnected')
                    except BaseException:
                        stop.set();raise

                async def process():
                    await endpoint_ready.wait()
                    await generate_reply(models,endpoint_pcm,mode,emit,event,stop,state)

                async def complete():
                    await processing
                    await input_done.wait()

                reader=asyncio.create_task(read_input());processing=asyncio.create_task(process())
                completion=asyncio.create_task(complete())
                async with asyncio.timeout(30):
                    done,_=await asyncio.wait([reader,completion],return_when=asyncio.FIRST_COMPLETED)
                    if reader in done:
                        await reader
                    await completion
                reason=state.get('finish_reason','unknown')
            except TimeoutError:
                reason='timeout';event('cancel_requested',cause='timeout')
            except (ConnectionResetError,asyncio.CancelledError):
                reason='client_disconnected'
            except Exception as exc:
                state['error']=type(exc).__name__+': '+str(exc);reason='error'
            finally:
                if reason not in ('stop','length'):
                    stop.set()
                for task in (reader,completion,processing):
                    if task and not task.done():task.cancel()
                cleanup=asyncio.gather(*(t for t in (reader,completion,processing) if t),return_exceptions=True)
                while not cleanup.done():
                    try:await asyncio.shield(cleanup)
                    except asyncio.CancelledError:stop.set()
                cleanup.result()
                event('turn_terminal',finish_reason=reason)
                record={'type':'terminal','session_id':session,'turn_id':turn,'generation_id':generation,
                    'finish_reason':reason,'state':state,'events':events,'input_complete':input_complete,
                    'input_samples':len(received)//2,'output_samples':sent_samples,
                    'input_pcm_sha256':hashlib.sha256(received).hexdigest(),
                    'output_pcm_sha256':hashlib.sha256(sent_pcm).hexdigest()}
                if session!='invalid' and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',session):
                    prefix=output/f'{session}-{turn}-{generation}'
                    prefix.with_suffix('.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
                    for label,data,rate in [('input',received,16000),('output',sent_pcm,24000)]:
                        with wave.open(str(prefix)+f'-{label}.wav','wb') as wav:
                            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(data)
                if not ws.closed:
                    try:await ws.send_json(record)
                    except (ConnectionResetError,RuntimeError):pass
                await ws.close()
        return ws

    async def index(request):
        return web.FileResponse(Path(__file__).with_name('client.html'))
    async def playback_script(request):
        return web.FileResponse(Path(__file__).with_name('playback.js'))
    async def manifest(request):
        return web.FileResponse(Path(__file__).parent/'audio/manifest.json')
    async def audio_file(request):
        name=request.match_info['name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.wav',name):raise web.HTTPNotFound()
        return web.FileResponse(Path(__file__).parent/'audio'/name)
    async def save_browser(request):
        body=await request.json()
        identity=body.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',identity):raise web.HTTPBadRequest()
        (output/f'browser-{identity}.json').write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
        return web.json_response({'saved':identity})
    app.router.add_get('/ws',ws_handler);app.router.add_get('/',index)
    app.router.add_get('/playback.js',playback_script)
    app.router.add_get('/manifest',manifest);app.router.add_get('/audio/{name}',audio_file)
    app.router.add_post('/browser-result',save_browser)
    return app


if __name__=='__main__':
    from models import Models
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18144)
    p.add_argument('--output',default='results/server');args=p.parse_args()
    models=Models()
    web.run_app(create_app(models,args.output),host='127.0.0.1',port=args.port)
