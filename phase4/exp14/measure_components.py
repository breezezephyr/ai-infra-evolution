"""CUDA smoke tests and independent warm timing. No transport latency claims."""
import argparse
import hashlib
import importlib.metadata as md
import json
import subprocess
import threading
import time
import wave
from pathlib import Path
from models import Models, pcm16, non_silent_sample


def gpu_mib():
    out = subprocess.check_output(['/usr/lib/wsl/lib/nvidia-smi',
        '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True)
    return int(out.strip().splitlines()[0])


def main(args):
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    parts = ('asr','llm','tts','vad') if args.component == 'resident' else (args.component,)
    before = gpu_mib()
    t0 = time.perf_counter()
    models = Models(parts)
    loaded = gpu_mib()
    model_load_ms = (time.perf_counter()-t0)*1000
    if loaded > 6656:
        raise RuntimeError('6.5 GiB budget exceeded after loading')
    with wave.open(args.audio) as wav:
        assert wav.getframerate()==16000 and wav.getnchannels()==1 and wav.getsampwidth()==2
        pcm = wav.readframes(wav.getnframes())
    text = '请用一句话解释什么是排队。'
    rows=[]
    peaks=[]
    monitoring=threading.Event()
    def monitor():
        while not monitoring.is_set():
            peaks.append(gpu_mib()); monitoring.wait(.2)
    monitor_thread=threading.Thread(target=monitor)
    monitor_thread.start()
    try:
        for repeat in range(args.repeats+1):
            row={'repeat':repeat,'warmup':repeat==0}
            if 'asr' in parts:
                models.torch.cuda.synchronize(); start=time.perf_counter()
                recognized=models.asr(pcm); models.torch.cuda.synchronize()
                row['asr']={'text':recognized,'ms':(time.perf_counter()-start)*1000}
            if 'llm' in parts:
                state={}; first=None; models.torch.cuda.synchronize(); start=time.perf_counter()
                chunks=[]
                for chunk in models.stream_text(text,threading.Event(),state):
                    if first is None:first=(time.perf_counter()-start)*1000
                    chunks.append(chunk)
                models.torch.cuda.synchronize()
                row['llm']={'text':''.join(chunks),'first_text_ms':first,'total_ms':(time.perf_counter()-start)*1000,**state}
            if 'tts' in parts:
                models.torch.cuda.synchronize(); start=time.perf_counter(); chunks=[]; first=None
                for chunk in models.tts('排队就是大家按先后顺序等待。'):
                    if first is None:first=(time.perf_counter()-start)*1000
                    chunks.append(chunk)
                models.torch.cuda.synchronize()
                audio=models.np.concatenate(chunks)
                audio_path=out/f'{args.component}-{repeat}.wav'
                with wave.open(str(audio_path),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm16(audio))
                row['tts']={'first_pcm_ms':first,'total_ms':(time.perf_counter()-start)*1000,
                            'samples':len(audio),'first_non_silent_sample':non_silent_sample(audio),
                            'wav':audio_path.name,'sha256':hashlib.sha256(audio_path.read_bytes()).hexdigest()}
            rows.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
    finally:
        monitoring.set();monitor_thread.join()
    result={'kind':'actual_cuda_component_smoke','component':args.component,
            'models':models.metadata,'before_mib':before,'loaded_mib':loaded,
            'observed_peak_mib':max(peaks,default=loaded),'model_load_ms':model_load_ms,
            'versions':{name:md.version(name) for name in ['torch','transformers','faster-whisper','ctranslate2','kokoro','misaki','silero-vad']},
            'records':rows}
    (out/f'{args.component}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if result['observed_peak_mib']>6656:raise RuntimeError('observed GPU budget exceeded')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--component',choices=['asr','llm','tts','resident'],required=True)
    p.add_argument('--audio',required=True);p.add_argument('--output',required=True);p.add_argument('--repeats',type=int,default=3)
    main(p.parse_args())
