"""Temporary loopback media bench. Fixed WAV replay, no model inference."""
import argparse
import asyncio
import fractions
import json
import re
import struct
import time
import wave
from pathlib import Path

import numpy as np
from aiohttp import web, WSMsgType
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from av import AudioFrame

ROOT = Path(__file__).resolve().parent
HEADER = struct.Struct('!4sIII')


def valid_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value):
        raise web.HTTPBadRequest(text='invalid run/session id')
    return value


class Trial:
    def __init__(self, output, run_id, fixture, transport, scenario):
        self.output=output;self.id=valid_id(run_id);self.fixture=fixture
        self.transport=transport;self.scenario=scenario
        self.events=[];self.produced=0;self.start=asyncio.Event();self.closed=False
        self.event('created')

    def event(self,name,**fields):
        self.events.append({'event':name,'clock_domain':'server_monotonic',
                            'monotonic_ns':time.perf_counter_ns(),**fields})

    def save(self):
        data={'run_id':self.id,'fixture_id':self.fixture['id'],'transport':self.transport,
              'scenario':self.scenario,'produced_samples':self.produced,
              'fixture_samples':self.fixture['samples'],'events':self.events}
        (self.output/f'server-{self.id}.json').write_text(json.dumps(data,indent=2)+'\n')


class ReplayTrack(AudioStreamTrack):
    def __init__(self, trial, pcm):
        super().__init__();self.trial=trial;self.pcm=pcm;self.index=0;self.origin=None
        self.paused=False;self.exhausted=False;self.on_done=lambda:None

    async def recv(self):
        await self.trial.start.wait()
        if self.origin is None:self.origin=time.perf_counter()
        if self.trial.scenario=='source_pause' and self.index==50 and not self.paused:
            self.trial.event('source_pause_begin',duration_ms=200)
            await asyncio.sleep(.2);self.origin+=.2;self.paused=True
            self.trial.event('source_pause_end')
        due=self.origin+self.index*.02
        await asyncio.sleep(max(0,due-time.perf_counter()))
        offset=self.index*960
        values=self.pcm[offset:offset+960]
        if len(values):
            self.trial.produced+=len(values)
            if self.index==0:self.trial.event('first_frame_supplied')
        else:
            values=np.zeros(960,dtype='<i2')
            if not self.exhausted:
                self.exhausted=True;self.trial.event('source_exhausted');self.on_done()
        frame=AudioFrame(format='s16',layout='mono',samples=960)
        frame.planes[0].update(values.tobytes());frame.sample_rate=48000
        frame.pts=offset;frame.time_base=fractions.Fraction(1,48000)
        self.index+=1
        return frame


def create_app(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((ROOT/'audio/manifest.json').read_text())
    fixtures={item['id']:item for item in manifest['fixtures']}
    audio={}
    for key,item in fixtures.items():
        with wave.open(str(ROOT/'audio'/item['file']),'rb') as f:
            assert f.getframerate()==48000 and f.getsampwidth()==2 and f.getnchannels()==1
            audio[key]=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').copy()
    app=web.Application(client_max_size=4*1024**2)
    trials={};pcs=set();sockets=set()

    def new_trial(data, transport):
        key=data.get('fixture','short');run=valid_id(data.get('run_id'))
        scenario=data.get('scenario','baseline')
        if key not in fixtures or scenario not in ('baseline','source_pause'):
            raise web.HTTPBadRequest(text='unknown fixture/scenario')
        if run in trials:raise web.HTTPConflict(text='duplicate run')
        trial=Trial(output,run,fixtures[key],transport,scenario);trials[run]=trial
        return trial,audio[key]

    async def index(request):return web.FileResponse(ROOT/'client.html')
    async def static(request):return web.FileResponse(ROOT/request.match_info['name'])
    async def fixture_info(request):return web.json_response(manifest)
    async def health(request):return web.json_response({'status':'ready','kind':'fixed_audio_transport','new_gpu_inferences':0,'trials':len(trials),'peer_connections':len(pcs),'websockets':len(sockets)})

    async def websocket(request):
        ws=web.WebSocketResponse(max_msg_size=10000,heartbeat=10)
        await ws.prepare(request);sockets.add(ws)
        trial=None;sender=None;last_ack=0
        try:
            data=await ws.receive_json(timeout=10)
            trial,pcm=new_trial(data,'ws')
            await ws.send_json({'type':'ready','fixture':trial.fixture,'buffer_samples':2880})

            async def send():
                await trial.start.wait();origin=time.perf_counter()
                for seq,offset in enumerate(range(0,len(pcm),960)):
                    if trial.scenario=='source_pause' and seq==50:
                        trial.event('source_pause_begin',duration_ms=200)
                        await asyncio.sleep(.2);origin+=.2;trial.event('source_pause_end')
                    await asyncio.sleep(max(0,origin+seq*.02-time.perf_counter()))
                    chunk=pcm[offset:offset+960]
                    await ws.send_bytes(HEADER.pack(b'P415',seq,offset,len(chunk))+chunk.tobytes())
                    trial.produced+=len(chunk)
                    if seq==0:trial.event('first_frame_sent')
                trial.event('source_exhausted')
                await ws.send_json({'type':'producer_done','samples':len(pcm)})
            sender=asyncio.create_task(send())
            async for msg in ws:
                if msg.type!=WSMsgType.TEXT:continue
                control=json.loads(msg.data);kind=control.get('type')
                if kind=='start':
                    if trial.start.is_set():raise ValueError('duplicate start')
                    trial.event('start_received');trial.start.set()
                elif kind=='ack':
                    ack=control.get('samples')
                    if type(ack) is not int or not last_ack<=ack<=trial.produced:
                        raise ValueError('invalid playback ACK')
                    last_ack=ack
                    if ack==len(pcm):trial.event('all_samples_acknowledged',samples=ack)
                else:raise ValueError('unknown WS control')
        except Exception as exc:
            if trial:trial.event('error',error=str(exc))
        finally:
            if sender:
                sender.cancel();await asyncio.gather(sender,return_exceptions=True)
            if trial:trial.event('socket_closed',last_ack=last_ack);trial.save()
            sockets.discard(ws)
        return ws

    async def offer(request):
        data=await request.json();trial,pcm=new_trial(data,'rtc')
        pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));pcs.add(pc)
        track=ReplayTrack(trial,pcm);sender=pc.addTrack(track)
        transceiver=next(t for t in pc.getTransceivers() if t.sender==sender)
        transceiver.setCodecPreferences([c for c in RTCRtpSender.getCapabilities('audio').codecs if c.mimeType.lower()=='audio/opus'])
        channel=None
        @pc.on('datachannel')
        def on_channel(dc):
            nonlocal channel
            channel=dc
            @dc.on('message')
            def message(raw):
                control=json.loads(raw)
                if control.get('type')=='start' and not trial.start.is_set():
                    trial.event('start_received');trial.start.set()
            def ready():
                dc.send(json.dumps({'type':'ready','fixture':trial.fixture}))
            if dc.readyState=='open':ready()
            else:dc.on('open',ready)
        def done():
            if channel and channel.readyState=='open':channel.send(json.dumps({'type':'producer_done','samples':len(pcm)}))
        track.on_done=done
        @pc.on('connectionstatechange')
        async def state_changed():
            trial.event('connection_state',state=pc.connectionState)
            if pc.connectionState in ('failed','closed'):
                track.stop();trial.save();pcs.discard(pc)
        @pc.on('iceconnectionstatechange')
        def ice_state():trial.event('ice_state',state=pc.iceConnectionState)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=data['sdp'],type=data['type']))
        await pc.setLocalDescription(await pc.createAnswer())
        trial.event('answer_ready',sdp=pc.localDescription.sdp)
        trial.save()
        return web.json_response({'sdp':pc.localDescription.sdp,'type':pc.localDescription.type})

    async def result(request):
        record=await request.json();run=valid_id(record.get('run_id'))
        dest=output/f'client-{run}.json'
        if dest.exists():raise web.HTTPConflict(text='result already saved')
        dest.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        if run in trials:trials[run].event('client_result_received');trials[run].save()
        return web.json_response({'saved':True})

    async def shutdown(app):
        await asyncio.gather(*(ws.close() for ws in list(sockets)),return_exceptions=True)
        await asyncio.gather(*(pc.close() for pc in list(pcs)),return_exceptions=True)
        for trial in trials.values():trial.save()

    app.router.add_get('/',index)
    app.router.add_get('/{name:client.js|worklet.js}',static)
    app.router.add_get('/fixtures.json',fixture_info);app.router.add_get('/health',health)
    app.router.add_get('/ws',websocket);app.router.add_post('/offer',offer);app.router.add_post('/results',result)
    app.on_shutdown.append(shutdown)
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=18145);p.add_argument('--output',required=True)
    args=p.parse_args();web.run_app(create_app(args.output),host=args.host,port=args.port,access_log=None)
