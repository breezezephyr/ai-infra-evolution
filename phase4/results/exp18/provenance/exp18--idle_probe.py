"""One bounded no-new-request window, with ASR/LLM resident on CUDA.

Not a whole-device inactivity claim. No service, port or persistent process.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'exp14'))
from models import Models


def now():
    return time.perf_counter_ns()


def gpu_sample():
    start = now()
    value = subprocess.check_output([
        '/usr/lib/wsl/lib/nvidia-smi',
        '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'
    ], text=True).strip()
    memory, utilization = map(int, value.split(','))
    return dict(started_ns=start, ended_ns=now(), memory_mib=memory,
                utilization_percent=utilization)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        raise ValueError('bounded probe requires 1..30 seconds')
    args.out.mkdir(parents=True, exist_ok=False)
    record = dict(schema='exp18-idle-v1', scope='one process, ASR and LLM only',
                  clock='server_monotonic', no_new_inference_requests_during_idle=True,
                  device_globally_idle=None, acoustic_latency_ms=None,
                  actual_billing=None, baseline=gpu_sample(), warmup_calls=[])
    started = now()
    models = Models(parts=('asr', 'llm'))
    record['models'] = models.metadata
    record['model_load_wall_ms'] = (now() - started) / 1e6
    wav = ROOT.parent / 'exp14/audio/short_03.wav'
    with wave.open(str(wav)) as source:
        assert source.getframerate() == 16000 and source.getsampwidth() == 2
        pcm = source.readframes(source.getnframes())
    record['input_pcm_sha256'] = hashlib.sha256(pcm).hexdigest()
    started = now()
    text = models.asr(pcm)
    record['warmup_calls'].append(dict(component='asr', started_ns=started,
                                      ended_ns=now(), text=text))
    started = now()
    state = {}
    output = ''.join(models.stream_text(text, threading.Event(), state))
    record['warmup_calls'].append(dict(component='llm', started_ns=started,
                                      ended_ns=now(), text=output, state=state))
    import torch
    torch.cuda.synchronize()
    record['idle_start_ns'] = now()
    samples = []
    deadline = record['idle_start_ns'] + int(args.seconds * 1e9)
    while now() < deadline:
        samples.append(gpu_sample())
        remaining = (deadline - now()) / 1e9
        if remaining > 0:
            time.sleep(min(0.25, remaining))
    record['idle_end_ns'] = now()
    record['samples'] = samples
    record['idle_seconds'] = (record['idle_end_ns'] - record['idle_start_ns']) / 1e9
    record['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.out / 'idle.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ['idle_seconds', 'models']}))


if __name__ == '__main__':
    main()
