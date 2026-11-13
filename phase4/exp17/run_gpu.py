"""Actual GPU prefix re-recognition and versioned speculative text generation.

Audio is supplied from a frozen WAV at 20ms cadence inside this process.
File completion is the explicit commit gate; no VAD, TTS, socket or microphone.
"""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'exp14'))
from models import Models
from logic import joined_call, normalized_cer
from revision import Gate, LatestInput, canonical

CASES=['short_03','pause_02','pause_03','long_02']


def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def now():return time.perf_counter_ns()


class Draft:
    def __init__(self,models,number,revision,text,on_piece,event):
        self.number,self.revision,self.text=number,revision,text
        self.stop=threading.Event();self.state={};self.started_ns=None;self.return_ns=None
        self.error=None;self.output='';self.event=event
        self.invalidated=False
        def work():
            iterator=None;self.started_ns=now();event('llm_start',draft_id=number,revision=revision,prompt=text)
            try:
                iterator=models.stream_text(text,self.stop,self.state)
                for piece in iterator:
                    if self.stop.is_set():break
                    self.output+=piece
                    on_piece(number,revision,piece)
            except BaseException as exc:self.error=repr(exc)
            finally:
                if iterator is not None:iterator.close()
                self.return_ns=now();event('llm_return',draft_id=number,revision=revision)
        self.thread=threading.Thread(target=work,name=f'exp17-draft-{number}',daemon=False)

    def start(self):self.thread.start()
    def join(self):self.thread.join()
    def record(self):
        return dict(draft_id=self.number,revision=self.revision,prompt=self.text,
            key=canonical(self.text),text_taken=self.output,state=self.state,
            started_ns=self.started_ns,returned_ns=self.return_ns,
            invalidated=self.invalidated,thread_stopped=not self.thread.is_alive(),error=self.error)


async def run_case(models,case,pcm,policy,run_id,cadence_ms):
    events=[];drafts=[];calls=[];gate=Gate(policy);slot=LatestInput();requested=asyncio.Event()
    source_done=False;input_end_ns=None;first_validated_ns=None;published=''
    loop=asyncio.get_running_loop();run_start=now();slip=[]
    def event(name,**fields):
        events.append(dict(event=name,session_id=run_id,turn_id=1,
            revision=fields.pop('revision',gate.revision),generation_id=fields.get('draft_id'),
            component=name.split('_')[0],clock_domain='server_monotonic',monotonic_ns=now(),**fields))
    def publish():
        nonlocal first_validated_ns,published
        if len(gate.published)>len(published):
            if first_validated_ns is None:first_validated_ns=now()
            event('validated_text_published',draft_id=gate.committed_draft,text=gate.published[len(published):])
            published=gate.published
    def on_piece(number,revision,piece):
        def deliver():
            accepted=gate.piece(number,piece)
            event('llm_piece',draft_id=number,revision=revision,text=piece,published=accepted)
            publish()
        loop.call_soon_threadsafe(deliver)
    async def retire(draft):
        if not draft.invalidated:
            draft.invalidated=True
            event('draft_invalidated',draft_id=draft.number,revision=draft.revision,
                  was_running=draft.thread.is_alive())
            draft.stop.set();event('llm_stop_set',draft_id=draft.number,revision=draft.revision)
        await joined_call(draft.join)
        event('llm_joined',draft_id=draft.number,revision=draft.revision)
        if draft.error:raise RuntimeError(draft.error)
    async def observe(text,final,offset):
        before=gate.key;old=drafts[-1] if drafts else None
        start_new=gate.observe(text,final=final)
        event('transcript_observed',text=text,key=gate.key,final=final,offset=offset,
              previous_key=before,stable_observations=gate.same)
        publish()
        if gate.key!=before and old is not None:await retire(old)
        if start_new:
            number=len(drafts)+1;gate.attach(number)
            draft=Draft(models,number,gate.revision,text,on_piece,event);drafts.append(draft);draft.start()
        if final:
            event('final_committed',draft_id=gate.committed_draft,text=text,offset=offset)
            publish()
    async def source():
        nonlocal source_done,input_end_ns
        total=len(pcm)//2;next_snapshot=cadence_ms*16
        for end in range(320,total+320,320):
            end=min(end,total);target=run_start+end*1_000_000_000//16000
            await asyncio.sleep(max(0,(target-now())/1e9))
            actual=now();slip.append((actual-target)/1e6)
            event('input_frame_available',offset=end,scheduled_ns=target)
            if policy!='endpoint' and end>=next_snapshot and end<total:
                slot.offer(end);requested.set();event('asr_snapshot_requested',offset=end,final=False)
                while next_snapshot<=end:next_snapshot+=cadence_ms*16
        source_done=True;input_end_ns=now();event('input_complete',offset=total)
        slot.offer(total,final=True);requested.set();event('asr_snapshot_requested',offset=total,final=True)
    async def recognition():
        while True:
            if slot.pending is None:await requested.wait()
            requested.clear();job=slot.take()
            if job is None:continue
            offset,final=job;start=now();event('asr_start',offset=offset,final=final)
            text=await joined_call(models.asr,pcm[:offset*2])
            end=now();event('asr_end',offset=offset,final=final,text=text)
            calls.append(dict(offset=offset,final=final,text=text,started_ns=start,ended_ns=end,wall_ms=(end-start)/1e6))
            if source_done and not final:
                event('asr_partial_superseded_by_final',offset=offset);continue
            await observe(text,final,offset)
            if final:break
    event('run_start',case_id=case['id'],policy=policy)
    error=None
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(source());group.create_task(recognition())
        active=next(d for d in drafts if d.number==gate.committed_draft)
        await joined_call(active.join)
        event('llm_joined',draft_id=active.number,revision=active.revision)
        if active.error:raise RuntimeError(active.error)
        await asyncio.sleep(0)  # drain already-posted piece callbacks before the terminal
        publish()
        if not published:raise RuntimeError('no validated text')
    except BaseException as exc:
        error=repr(exc)
    finally:
        for draft in drafts:
            if draft.thread.is_alive():draft.stop.set()
        for draft in drafts:
            await joined_call(draft.join)
        await asyncio.sleep(0)
        event('all_workers_joined',workers=len(drafts))
    final_call=next((c for c in calls if c['final']),None)
    final_key=canonical(final_call['text']) if final_call else None
    committed=gate.committed_draft
    return dict(run_id=run_id,case_id=case['id'],policy=policy,error=error,
        source=dict(samples=len(pcm)//2,sample_rate=16000,pcm_sha256=hashlib.sha256(pcm).hexdigest(),
            duration_ms=len(pcm)/32,reference_text=case['reference_text'],source='frozen macOS Tingting WAV',
            clock='server_monotonic',run_start_ns=run_start,input_complete_ns=input_end_ns,
            source_delivery_lateness_ms=slip),
        cadence_ms=cadence_ms,asr_calls=calls,asr_pending_replaced=slot.replaced,
        asr_cumulative_input_samples=sum(c['offset'] for c in calls),
        asr_call_wall_ms=sum(c['wall_ms'] for c in calls),
        final_text=final_call['text'] if final_call else None,final_key=final_key,
        final_cer=normalized_cer(case['reference_text'],final_call['text']) if final_call else None,
        first_validated_text_ns=first_validated_ns,validated_text=published,committed_draft=committed,
        first_validated_after_input_end_ms=(first_validated_ns-input_end_ns)/1e6 if first_validated_ns and input_end_ns else None,
        committed_draft_started_before_input_end=(next((d.started_ns for d in drafts if d.number==committed),now())<input_end_ns) if input_end_ns else None,
        wasted_generated_tokens=sum(d.state.get('generated_tokens',0) for d in drafts if d.number!=committed),
        total_generated_tokens=sum(d.state.get('generated_tokens',0) for d in drafts),
        rejected_piece_count=gate.rejected_pieces,drafts=[d.record() for d in drafts],
        events=sorted(events,key=lambda e:e['monotonic_ns']),elapsed_ms=(now()-run_start)/1e6,
        microphone_input=False,native_streaming_asr=False,tts_audio=None,acoustic_latency_ms=None)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--repeat',type=int,default=3);parser.add_argument('--cadence-ms',type=int,default=800)
    parser.add_argument('--warmup',type=int,default=1)
    parser.add_argument('--cases',nargs='+',default=CASES)
    parser.add_argument('--policies',nargs='+',default=['endpoint','eager','stable2'])
    args=parser.parse_args();output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    monitor_stop=threading.Event();resources=[]
    def resource_monitor():
        while not monitor_stop.is_set():
            proc=subprocess.run(['/usr/lib/wsl/lib/nvidia-smi','--query-gpu=memory.used,utilization.gpu',
                '--format=csv,noheader,nounits'],capture_output=True,text=True)
            if proc.returncode==0:
                memory,utilization=map(int,proc.stdout.strip().split(','));resources.append(dict(monotonic_ns=now(),memory_mib=memory,utilization_percent=utilization))
            monitor_stop.wait(.5)
    monitor=threading.Thread(target=resource_monitor,name='exp17-resource',daemon=False);monitor.start()
    try:
        models=Models(parts=('asr','llm'))
        manifest=json.loads((ROOT.parent/'exp14/audio/manifest.json').read_text())
        manifest_cases={c['id']:c for c in manifest['cases']}
        case_list=json.loads((ROOT.parent/'exp14/cases.json').read_text())['cases']
        cases={c['id']:c for c in case_list};inputs={}
        for name in args.cases:
            path=ROOT.parent/'exp14/audio'/f'{name}.wav'
            if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest_cases[name]['sha256']:
                raise ValueError('frozen input hash mismatch')
            with wave.open(str(path)) as audio:
                if (audio.getframerate(),audio.getsampwidth(),audio.getnchannels())!=(16000,2,1):raise ValueError('invalid audio')
                inputs[name]=audio.readframes(audio.getnframes())
            if len(inputs[name])//2!=manifest_cases[name]['samples']:raise ValueError('frozen input sample mismatch')
        hashes={str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [ROOT/'run_gpu.py',ROOT/'revision.py',ROOT.parent/'exp14/models.py',ROOT.parent/'exp14/logic.py']}
        save(output/'environment.json',dict(date='2026-10-23',models=models.metadata,source_sha256=hashes,
            packages={p:importlib.metadata.version(p) for p in ['torch','transformers','faster-whisper','ctranslate2']},
            config=vars(args),inputs={name:dict(wav_sha256=hashlib.sha256((ROOT.parent/'exp14/audio'/f'{name}.wav').read_bytes()).hexdigest(),
                pcm_sha256=hashlib.sha256(pcm).hexdigest(),samples=len(pcm)//2) for name,pcm in inputs.items()},
            scope='paced frozen audio, prefix re-recognition, gated LLM text; no TTS/microphone/VAD'))
        warmups=[]
        for repeat in range(args.warmup):
            for name,pcm in inputs.items():
                start=now();text=models.asr(pcm);state={};stop=threading.Event()
                reply=''.join(models.stream_text(text,stop,state))
                warmups.append(dict(case_id=name,repeat=repeat,asr_text=text,reply=reply,state=state,wall_ms=(now()-start)/1e6))
                save(output/'warmups.json',warmups)
                print(json.dumps(dict(warmup=name,repeat=repeat,wall_ms=warmups[-1]['wall_ms'])),flush=True)
        records=[]
        for repeat in range(args.repeat):
            for index,name in enumerate(args.cases):
                order=args.policies if (repeat+index)%2==0 else list(reversed(args.policies))
                for policy in order:
                    run_id=f'{output.name}-{name}-{policy}-r{repeat}'
                    result=asyncio.run(run_case(models,cases[name],inputs[name],policy,run_id,args.cadence_ms))
                    result['repeat']=repeat;save(output/f'{run_id}.json',result);records.append(result)
                    save(output/'records.json',dict(records=records))
                    print(json.dumps(dict(run_id=run_id,error=result['error'],asr_calls=len(result['asr_calls']),
                        drafts=len(result['drafts']),wasted_tokens=result['wasted_generated_tokens'],
                        final_text=result['final_text'],validated_text_ms=result['first_validated_after_input_end_ms'])),flush=True)
                    if result['error']:raise RuntimeError(result['error'])
    finally:
        monitor_stop.set();monitor.join();save(output/'gpu-samples.json',resources)


if __name__=='__main__':main()
