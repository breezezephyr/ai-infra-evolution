"""固定 exp14 输出为媒体载荷，增加可观察的首尾探针；不是新增模型推理。"""
import argparse
import hashlib
import json
import wave
from pathlib import Path
import numpy as np


def prepare(source, name, target):
    source = Path(source)
    with wave.open(str(source), 'rb') as f:
        rate, channels, width, count = f.getframerate(), f.getnchannels(), f.getsampwidth(), f.getnframes()
        if channels != 1 or width != 2:
            raise ValueError('expected mono PCM16 source')
        pcm = np.frombuffer(f.readframes(count), dtype='<i2').astype(np.float64)
    out_rate = 48000
    # 固定线性重采样后，两条传输路径使用同一份 48k PCM。
    n = round(len(pcm) * out_rate / rate)
    samples = np.interp(np.arange(n) * rate / out_rate, np.arange(len(pcm)), pcm)
    def tone(hz, seconds):
        t = np.arange(round(seconds*out_rate)) / out_rate
        return 0.16 * 32767 * np.sin(2*np.pi*hz*t)
    prefix = np.concatenate((tone(1000, .08), np.zeros(round(.12*out_rate))))
    suffix = np.concatenate((np.zeros(round(.12*out_rate)), tone(2000, .10), np.zeros(round(.30*out_rate))))
    all_pcm = np.rint(np.concatenate((prefix, samples, suffix))).clip(-32768,32767).astype('<i2')
    # 对齐 20ms。尾部补零仍是测试载荷的一部分。
    all_pcm = np.pad(all_pcm, (0, (-len(all_pcm)) % 960))
    target = Path(target); target.mkdir(parents=True, exist_ok=True)
    dest = target / f'{name}.wav'
    with wave.open(str(dest),'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(out_rate); f.writeframes(all_pcm.tobytes())
    return {'id':name,'file':dest.name,'source':str(source.resolve()),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'source_rate':rate,'source_samples':count,'source_seconds':count/rate,
            'rate':out_rate,'samples':len(all_pcm),'seconds':len(all_pcm)/out_rate,
            'pcm_sha256':hashlib.sha256(all_pcm.tobytes()).hexdigest(),
            'wav_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
            'prefix_seconds':.2,'start_probe_hz':1000,'end_probe_hz':2000,
            'end_probe_duration_seconds':.1,'tail_guard_seconds':.3}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--short',required=True);p.add_argument('--long',required=True);p.add_argument('--output',default=str(Path(__file__).parent/'audio'))
    args=p.parse_args();out=Path(args.output)
    fixtures=[prepare(args.short,'short',out),prepare(args.long,'long',out)]
    (out/'manifest.json').write_text(json.dumps({'purpose':'transport replay of exp14 GPU outputs with synthetic boundary probes','fixtures':fixtures},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(fixtures,ensure_ascii=False))
