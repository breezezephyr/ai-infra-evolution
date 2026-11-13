"""Build the per-case matrix from the recorded formal native-library run."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from audit import summarize

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument('results',type=Path);args=parser.parse_args()
    cases=json.loads((ROOT/'cases.json').read_text())['cases']
    rows=json.loads((args.results/'records.json').read_text())['records']
    run_meta=json.loads((args.results/'summary.json').read_text())
    for name,digest in run_meta['code_sha256'].items():
        assert hashlib.sha256((args.results/'provenance'/name).read_bytes()).hexdigest()==digest
    summary=summarize(cases,rows)
    fields=['id','protocol','family','conversion','conformance','model_version','input_max_tokens','converted_max_tokens',
            'temperature','top_p','stop_sequences','prompt_tokens','checks_pass','checks_fail','checks_unknown']
    outcomes={o['id']:o for o in summary['outcomes']}
    matrix=[]
    for row in rows:
        facts=row.get('facts',{});body=row['input'];checks=row['checks']
        matrix.append(dict(id=row['id'],protocol=row['protocol'],family=row['family'],conversion=row['conversion']['status'],
            conformance=outcomes[row['id']]['status'],model_version=facts.get('model_version'),
            input_max_tokens=body.get('max_output_tokens') if row['protocol']=='responses' else body.get('max_tokens'),
            converted_max_tokens=facts.get('max_tokens'),temperature=facts.get('temperature'),top_p=facts.get('top_p'),
            stop_sequences=json.dumps(facts.get('stop_sequences'),ensure_ascii=False),prompt_tokens=row.get('encoding',{}).get('prompt_tokens'),
            checks_pass=sum(c['status']=='pass' for c in checks),checks_fail=sum(c['status']=='fail' for c in checks),
            checks_unknown=sum(c['status']=='unknown' for c in checks)))
    out=args.results.parent
    with (out/'capability-matrix.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(matrix)
    report=dict(schema='exp19-audit-v1',date='2026-10-23',**summary,
        scope='actual recipe native library; no model inference, tools, HTTP service or model quality claims',
        matrix=matrix,
        sources=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
                 [ROOT/'cases.json',args.results/'provenance/run.py',args.results/'provenance/audit.py',args.results/'provenance/cases.json',args.results/'records.json']],
        source_commit='935817c66f5d6e64838f419692545f06787e485f',
        executed_distribution='deepseek-recipe 0.2.0 official macOS ARM64 wheel',
        binary_built_from_source_commit=None,model_inference_calls=0)
    (out.parent/'exp19-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['n','accepted','rejected','conformant','failed','unknown','requested_check_count','check_counts']},ensure_ascii=False))


if __name__=='__main__':main()
