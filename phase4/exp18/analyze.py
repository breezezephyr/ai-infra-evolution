"""Recompute the four original experiments with their original boundaries."""
import hashlib
import json
from pathlib import Path
from accounting import extract as resources
from experience import extract as experience
from interruption import extract as interruption

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/exp18'


def main():
    OUT.mkdir(exist_ok=True)
    ledgers={'experience':experience(ROOT),'interruption':interruption(ROOT),'resource':resources(ROOT)}
    for name, value in ledgers.items():
        (OUT/f'{name}-audit.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    contract=ROOT/'exp18/metric-contract.json'
    summary=dict(schema='exp18-v1',date='2026-10-23',
        scope='independent experiment ledgers, not joint production session SLO',
        **ledgers,
        metric_contract=dict(path=str(contract.relative_to(ROOT)),sha256=hashlib.sha256(contract.read_bytes()).hexdigest()),
        new_gpu_inference=dict(asr_warmup_calls=1,llm_warmup_calls=1,tts_calls=0,
                               no_new_request_window_n=1),
        actual_bill=None,actual_session_minutes=None,production_slo_attainment=None,
        acoustic_latency_ms=None,concurrent_capacity=None)
    path=ROOT/'results/exp18-summary.json'
    path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(path)


if __name__=='__main__':
    main()
