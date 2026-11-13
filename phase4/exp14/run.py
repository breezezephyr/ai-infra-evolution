"""Paced file-to-live-CUDA WebSocket client. Capture only: no playback claims."""
import argparse
import asyncio
import hashlib
import json
import time
import wave
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, WSMsgType
from protocol import pack_audio, unpack_audio, SequenceGuard


async def run_one(client, url, case, audio_dir, out, mode, repeat, number, warmup=False):
    identity=f'{out.name}-{case["id"]}-r{repeat}-{mode}-{number}'
    pcm_path=audio_dir/case['wav']
    if hashlib.sha256(pcm_path.read_bytes()).hexdigest()!=case['sha256']:
        raise ValueError('input hash mismatch')
    with wave.open(str(pcm_path)) as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
            raise ValueError('invalid input WAV')
        pcm=wav.readframes(wav.getnframes())
    result={'id':identity,'case_id':case['id'],'category':case['category'],
            'reference_text':case['reference_text'],'input_sha256':case['sha256'],
            'input_pcm_sha256':hashlib.sha256(pcm).hexdigest(),
            'mode':mode,'repeat':repeat,'warmup':warmup,'kind':'paced_input_capture_only',
            'client_clock_domain':'client_monotonic','first_pcm_received_ns':None,
            'first_non_silent_received_ns':None,'first_non_silent_render_ms':None,
            'device_output_estimate_ms':None,'acoustic_first_sound_ms':None,
            'input_frames':[],'output_frames':[],'terminal':None}
    output=bytearray();last_speech=case['speech_intervals'][-1]['end']
    guard=SequenceGuard(number,1,24000*30)
    sender=None
    try:
        async with client.ws_connect(url+'/ws',max_msg_size=4*1024*1024) as ws:
            await ws.send_json({'type':'start','session_id':identity,'turn_id':number,
                               'generation_id':1,'mode':mode,'playback':'capture_only'})
            ready=await ws.receive_json()
            if ready.get('type')!='ready':raise RuntimeError('server did not accept turn')
            result['ready']=ready
            start=time.perf_counter_ns();result['input_start_ns']=start
            result['reference_input_end_ns']=start+round(last_speech/16000*1e9)
            async def send():
                for seq,offset in enumerate(range(0,len(pcm)//2,320)):
                    part=pcm[offset*2:(offset+320)*2]
                    deadline=start+round((offset+len(part)//2)/16000*1e9)
                    await asyncio.sleep(max(0,(deadline-time.perf_counter_ns())/1e9))
                    await ws.send_bytes(pack_audio(number,1,seq,offset,part))
                    result['input_frames'].append({'offset':offset,'samples':len(part)//2,
                        'sent_ns':time.perf_counter_ns(),'scheduled_end_ns':deadline})
                await ws.send_json({'type':'input_end'})
                result['input_sent_complete_ns']=time.perf_counter_ns()
            sender=asyncio.create_task(send())
            async with asyncio.timeout(45):
                async for msg in ws:
                    now=time.perf_counter_ns()
                    if msg.type==WSMsgType.BINARY:
                        f=unpack_audio(msg.data)
                        if not guard.accept(f):continue
                        if result['first_pcm_received_ns'] is None:result['first_pcm_received_ns']=now
                        if result['first_non_silent_received_ns'] is None:
                            import struct
                            if any(abs(v)>=328 for (v,) in struct.iter_unpack('<h',f.pcm)):
                                result['first_non_silent_received_ns']=now
                        output.extend(f.pcm)
                        result['output_frames'].append({'offset':f.sample_offset,'samples':len(f.pcm)//2,'received_ns':now})
                        await ws.send_json({'type':'ack','samples':f.sample_offset+len(f.pcm)//2})
                    elif msg.type==WSMsgType.TEXT:
                        data=json.loads(msg.data)
                        if data.get('type')=='terminal':result['terminal']=data;break
            if sender and not sender.done():
                await sender
            elif sender:
                sender.result()
    except Exception as exc:
        result['client_error']=type(exc).__name__+': '+str(exc)
    finally:
        if sender and not sender.done():sender.cancel()
        if sender:await asyncio.gather(sender,return_exceptions=True)
    result['output_samples']=len(output)//2
    result['output_pcm_sha256']=hashlib.sha256(output).hexdigest()
    terminal=result['terminal'] or {}
    endpoints=[e for e in terminal.get('events',[]) if e['event']=='endpoint_confirmed']
    result['endpoint_early']=bool(endpoints and endpoints[0]['sample_offset']<last_speech)
    if result['first_pcm_received_ns'] is not None:
        result['replay_end_to_first_pcm_ms']=(result['first_pcm_received_ns']-result['reference_input_end_ns'])/1e6
    else:result['replay_end_to_first_pcm_ms']=None
    if terminal.get('output_pcm_sha256') and terminal['output_pcm_sha256']!=result['output_pcm_sha256']:
        result['client_error']='output hash differs from server'
    with wave.open(str(out/f'{identity}.wav'),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(output)
    (out/f'{identity}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'case':case['id'],'mode':mode,'warmup':warmup,
        'finish':terminal.get('finish_reason'),'early':result['endpoint_early'],
        'first_pcm_ms':result['replay_end_to_first_pcm_ms'],'samples':result['output_samples'],
        'error':result.get('client_error')},ensure_ascii=False),flush=True)
    return result


async def main(args):
    audio=Path(args.audio);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((audio/'manifest.json').read_text())
    cases=[c for c in manifest['cases'] if args.case=='all' or c['id']==args.case]
    if not cases:raise ValueError('case not found')
    results_file=out/'records.jsonl'
    if results_file.exists():raise ValueError('output already exists; use a new directory')
    number=0
    async with ClientSession(timeout=ClientTimeout(total=50)) as client:
        with results_file.open('w') as log:
            for warm in range(args.warmup):
                for mode in args.modes:
                    number+=1
                    row=await run_one(client,args.url,cases[0],audio,out,mode,warm,number,True)
                    log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
            for i,case in enumerate(cases):
                for repeat in range(args.repeats):
                    modes=list(args.modes);shift=(i+repeat)%len(modes);modes=modes[shift:]+modes[:shift]
                    for mode in modes:
                        number+=1
                        row=await run_one(client,args.url,case,audio,out,mode,repeat,number)
                        log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:18144')
    p.add_argument('--audio',default=str(Path(__file__).parent/'audio'));p.add_argument('--output',required=True)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--warmup',type=int,default=1)
    p.add_argument('--modes',default='ABC');p.add_argument('--case',default='all')
    asyncio.run(main(p.parse_args()))
