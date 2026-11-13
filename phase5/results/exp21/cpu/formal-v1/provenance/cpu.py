"""exp21: real recipe CPU conversion; source-derived backend candidates only.

Run with phase5/.venv-exp19/bin/python; no dependencies are installed.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import zipfile

import deepseek_recipe as recipe

ROOT = Path(__file__).resolve().parent
PHASE = ROOT.parent
REQUEST = {'chat': recipe.ChatCompletionRequest, 'responses': recipe.ResponsesRequest,
           'messages': recipe.MessagesRequest}
RECIPE_COMMIT = '935817c66f5d6e64838f419692545f06787e485f'
DEEPINFER_COMMIT = '9bd9cf243fc53ef9afbf8f04d391d989117d6ab9'


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def backend_mapping(constraint):
    """Fail closed. This builds reviewable candidates, never calls DeepInfer."""
    result = {'decision': 'reject', 'so_args': None, 'executed': False,
              'evidence_level': 'source_mapping_only', 'compiler_commit': DEEPINFER_COMMIT}
    if constraint is None:
        return {**result, 'decision': 'none', 'reason': 'No converted constraint.'}
    kind, schema = constraint['kind'], constraint['schema']
    if kind == 'json' and schema == '':
        return {**result, 'reason': 'recipe any-JSON empty sentinel needs an explicit grammar/schema policy; do not forward empty schema.'}
    if kind in {'json', 'regex'}:
        return {**result, 'decision': 'candidate', 'so_args': {'schema_type': kind, 'schema': schema},
                'reason': 'Compiler dispatch name matches; compilation, schema dialect, tokenizer, thinking trigger, EOS and sampling are unverified.'}
    return {**result, 'reason': 'No tool-call/unknown-kind adapter. Tool-list JSON is not a JSON Schema or model-specific EBNF.'}


def snapshot(request):
    conv, inf, parse = request.conversation, request.inference_options, request.parsing_options
    constraint = inf.output_constraint
    encoding = (recipe.DeepseekV41Encoding() if request.model_version == recipe.ModelVersion.DeepseekV41Flash
                else recipe.DeepseekV4Encoding())
    rendered = encoding.render_conversation(conv)
    return {'output_constraint': None if constraint is None else {'kind': constraint.kind, 'schema': constraint.schema},
            'constraint_schema_json': (json.loads(constraint.schema) if constraint is not None
                                       and constraint.kind == 'json' and constraint.schema else None),
            'model_version': str(request.model_version), 'thinking_mode': conv.thinking_mode,
            'tool_choice': conv.tool_choice,
            'tools': [{'name': t.name, 'parameters': t.parameters, 'strict': t.strict,
                       'defer_loading': t.defer_loading} for t in conv.tools],
            'response_format': conv.response_format, 'response_schema': conv.response_schema,
            'response_regex': conv.response_regex,
            'parsing_options': {key: getattr(parse, key) for key in
                                ('parse_json_output', 'parse_tool_calls', 'starts_in_tool_calls')},
            'rendered_prompt': rendered.prompt, 'rendered_prompt_sha256': hashlib.sha256(rendered.prompt.encode()).hexdigest(),
            'special_ranges': rendered.special_ranges}


def error(exc, stage):
    return {'stage': stage, 'type': type(exc).__name__, 'message': str(exc),
            'body': getattr(exc, 'body', None), 'status_code': getattr(exc, 'status_code', None)}


def field(value, path):
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def assess(case, row):
    expected = case.get('expect')
    if not expected:
        return 'unknown', ['No frozen expectation.']
    differences = []
    if row['outcome'] != expected['outcome']:
        differences.append(f"outcome: expected {expected['outcome']}, got {row['outcome']}")
    if row['outcome'] == 'rejected' and expected['outcome'] == 'rejected':
        err = row['error']
        for key, actual in [('stage', err['stage']), ('error_type', err['type']), ('status_code', err['status_code'])]:
            if key in expected and actual != expected[key]:
                differences.append(f'{key}: expected {expected[key]!r}, got {actual!r}')
        if 'message_contains' in expected and expected['message_contains'] not in err['message'] + (err['body'] or ''):
            differences.append('Expected rejection message did not match.')
    if row['outcome'] == 'accepted' and expected['outcome'] == 'accepted':
        view = row['snapshot']; constraint = view['output_constraint']
        actual = None if constraint is None else constraint['kind']
        if actual != expected.get('constraint_kind'):
            differences.append(f"constraint_kind: expected {expected.get('constraint_kind')!r}, got {actual!r}")
        for path, want in expected.get('facts', {}).items():
            try:
                got = field(view, path)
            except (KeyError, IndexError, TypeError):
                differences.append(f'Missing fact: {path}')
                continue
            if got != want:
                differences.append(f'{path}: expected {want!r}, got {got!r}')
    return ('fail' if differences else 'pass'), differences


def run_case(case, observer=None):
    start = time.perf_counter_ns()
    row = {'id': case['id'], 'protocol': case['protocol'], 'family': case['family'],
           'input': case['input'], 'expect': case.get('expect'), 'case_sha256': identity(case),
           'outcome': 'unexpected_error', 'snapshot': None, 'error': None,
           'execution': {'sampling_executed': False, 'compiler_executed': False,
                         'schema_instance_validated': False, 'tool_executed': False}}
    stage = 'dispatch'
    try:
        constructor = REQUEST[case['protocol']]
        stage = 'parse'
        request = constructor(case['input'])
        stage = 'convert'
        converted = request.convert(recipe.ConversionOptions())
        # Observation errors must not be mistaken for an expected native rejection.
        stage = 'observe'
        row['snapshot'] = (observer or snapshot)(converted)
        stage = 'mapping'
        row['backend_mapping'] = backend_mapping(row['snapshot']['output_constraint'])
        row['outcome'] = 'accepted'
    except Exception as exc:
        row['error'] = error(exc, stage)
        native_rejection = ((stage == 'parse' and isinstance(exc, (ValueError, recipe.ConversionError)))
                            or (stage == 'convert' and isinstance(exc, recipe.ConversionError)))
        row['outcome'] = 'rejected' if native_rejection else 'unexpected_error'
    row['verdict'], row['differences'] = assess(case, row)
    row['elapsed_ns'] = time.perf_counter_ns() - start
    return row


def summarize(cases, rows):
    counts = Counter(row['id'] for row in rows)
    ids = [case['id'] for case in cases]; expected = set(ids)
    by_id = {row['id']: row for row in rows}
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    missing = sorted(expected - set(counts)); extra = sorted(set(counts) - expected)
    mismatches = []; passed = 0; verdicts = Counter(); outcomes = Counter(); rejections = 0
    for case in cases:
        key = case['id']
        if key in missing or key in duplicates:
            verdicts['unknown'] += 1
            continue
        row = by_id[key]
        if row.get('case_sha256') != identity(case):
            mismatches.append(key); verdicts['unknown'] += 1
            continue
        try:
            verdict, _ = assess(case, row)
        except (KeyError, TypeError, IndexError):
            verdict = 'unknown'
        verdicts[verdict] += 1; outcomes[row['outcome']] += 1
        passed += verdict == 'pass'
        rejections += verdict == 'pass' and row['outcome'] == 'rejected'
    return {'configured': len(cases), 'recorded': len(rows), 'passed': passed,
            'failed': verdicts['fail'], 'unknown': verdicts['unknown'],
            'accepted': outcomes['accepted'], 'native_rejections': outcomes['rejected'],
            'expected_rejections': rejections, 'unexpected_errors': outcomes['unexpected_error'],
            'missing_ids': missing, 'duplicate_ids': duplicates, 'extra_ids': extra,
            'duplicate_case_ids': sorted(k for k, v in Counter(ids).items() if v > 1),
            'identity_mismatch_ids': mismatches,
            'ok': passed == len(cases) and not (missing or duplicates or extra or mismatches or len(ids) != len(expected)),
            'scope': 'CPU conversion contracts only; accepted is not executed or instance-validated'}


def parse_probe(case, raw):
    """Real StreamProcessor over explicitly synthetic backend text, no sampling."""
    row = {'case_id': case['id'], 'protocol': case['protocol'], 'raw': raw,
           'sampling_executed': False, 'schema_instance_validated': False,
           'backend_kind': 'synthetic_text_fixture', 'events': [], 'error': None,
           'json_value': None, 'text': None, 'finish_source': 'fixture_Stop',
           'usage_source': 'unmeasured; no token counts asserted'}
    processor = None; stage = 'convert'
    try:
        protocol = case['protocol']; cls = REQUEST[protocol]
        request = cls(case['input']).convert(recipe.ConversionOptions())
        row['snapshot'] = snapshot(request)
        response_cls = {'chat': recipe.ChatCompletionResponse, 'responses': recipe.ResponsesResponse,
                        'messages': recipe.MessagesResponse}[protocol]
        options = request.parsing_options
        stage = 'parser_construction'
        processor = recipe.StreamProcessor(cls.chunk_generator(request, 'exp21-cpu', 'DeepSeek-V4.1-Flash'), options)
        response = response_cls('exp21-cpu', 'DeepSeek-V4.1-Flash', 0, 0, 0)
        def emit(outputs):
            for output in outputs:
                row['events'].append(json.loads(output.to_json()))
                response.accumulate(output)
        stage = 'parser_text'
        emit(processor.push(recipe.InferenceChunk.text(raw)))
        row['finished_after_text'] = processor.finished
        stage = 'parser_finish'
        if not processor.finished:
            emit(processor.push(recipe.InferenceChunk.finish(recipe.InferenceFinishReason.Stop)))
        emit(processor.finish())
        row['native_finished'] = processor.finished
        stage = 'response_observation'
        body = json.loads(response.to_json()); row['response'] = body
        if protocol == 'chat':
            row['text'] = body['choices'][0]['message'].get('content') or ''
        elif protocol == 'responses':
            row['text'] = ''.join(part.get('text', '') for item in body.get('output', [])
                                  if item['type'] == 'message' for part in item.get('content', []))
        else:
            row['text'] = ''.join(item['text'] for item in body.get('content', []) if item['type'] == 'text')
        try:
            row['json_value'] = json.loads(row['text'])
            row['json_parseable'] = True
        except ValueError as exc:
            row['json_parseable'] = False; row['json_parse_error'] = str(exc)
    except Exception as exc:
        row['error'] = error(exc, stage)
    finally:
        if processor is not None:
            processor.close()
    return row


def assess_probe(probe, row):
    expected = probe.get('expect', {})
    if not expected or any(key not in row for key in expected):
        return 'unknown'
    return 'pass' if all(row[key] == want for key, want in expected.items()) else 'fail'


def invariant(name, eligible, predicate):
    passed = 0; failed = []; unknown = []
    for row in eligible:
        try:
            if predicate(row):
                passed += 1
            else:
                failed.append(row['id'])
        except Exception:
            unknown.append(row['id'])
    return {'name': name, 'applicable': len(eligible), 'passed': passed,
            'failed_ids': failed, 'unknown_ids': unknown,
            'status': 'fail' if failed else ('unknown' if unknown or not eligible else 'pass'),
            'scope': 'candidate invariant of these frozen CPU cases only'}


def export_contracts(out, rows, probe_rows):
    accepted = [r for r in rows if r['outcome'] == 'accepted']
    tool = [r for r in accepted if (r['snapshot']['output_constraint'] or {}).get('kind', '').startswith('tool_call')]
    empty = [r for r in accepted if r['snapshot']['output_constraint'] == {'kind': 'json', 'schema': ''}]
    checks = [
        invariant('CPU records never claim backend execution', rows,
                  lambda r: not any(r['execution'].values())),
        invariant('Tool constraint lists match converted tool names and required flag', tool,
                  lambda r: [t['function']['name'] for t in json.loads(r['snapshot']['output_constraint']['schema'])]
                  == [t['name'] for t in r['snapshot']['tools']]
                  and (r['snapshot']['output_constraint']['kind'] == 'tool_call_required')
                  == (r['snapshot']['tool_choice'] == 'required')),
        invariant('No tool-call kind is forwarded to DeepInfer compiler', tool,
                  lambda r: r['backend_mapping']['decision'] == 'reject' and r['backend_mapping']['so_args'] is None),
        invariant('Empty any-JSON sentinel is not forwarded as a JSON Schema', empty,
                  lambda r: r['backend_mapping']['decision'] == 'reject' and r['backend_mapping']['so_args'] is None),
        invariant('tool_choice none removes tool definitions and tool constraint',
                  [r for r in accepted if r['snapshot']['tool_choice'] == 'none'],
                  lambda r: not r['snapshot']['tools'] and not (r['snapshot']['output_constraint'] or {}).get('kind', '').startswith('tool_call')),
        invariant('Messages attempted format fields leave text format and no constraint',
                  [r for r in rows if r['protocol'] == 'messages' and r['family'] in {'format', 'unsupported-field'}],
                  lambda r: r['outcome'] == 'accepted' and r['snapshot']['response_format'] == 'text'
                  and r['snapshot']['output_constraint'] is None),
        invariant('Strict response schema normalizes constraint while preserving prompt schema',
                  [r for r in rows if r['id'] in {'chat-schema-strict', 'responses-schema-strict'}],
                  lambda r: 'required' not in r['snapshot']['response_schema']
                  and r['snapshot']['constraint_schema_json']['required'] == ['city']
                  and r['snapshot']['constraint_schema_json']['additionalProperties'] is False),
        invariant('Recognized invalid schemas reject during conversion',
                  [r for r in rows if r['protocol'] != 'messages' and any(r['id'].endswith(s) for s in
                   ['schema-invalid-type', 'schema-invalid-properties', 'schema-strict-scalar', 'schema-strict-empty'])],
                  lambda r: r['outcome'] == 'rejected' and r['error']['stage'] == 'convert'
                  and r['error']['status_code'] == 400),
        invariant('Strict-schema counterexamples pass through parser without instance validation',
                  [r for r in probe_rows if '-schema-' in r['id'] and r['protocol'] != 'messages'],
                  lambda r: r['error'] is None and r['text'] == r['raw'] and not r['schema_instance_validated']),
    ]
    write_json(out / 'candidate-invariants.json', checks)
    with (out / 'mapping-matrix.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'protocol', 'declaration', 'conversion', 'kind', 'schema',
                                                   'mapping_decision', 'candidate_so_args', 'transport', 'sampling',
                                                   'instance_validation', 'error'])
        writer.writeheader()
        for row in rows:
            view = row['snapshot'] or {}; constraint = view.get('output_constraint') or {}; mapping = row.get('backend_mapping', {})
            body = row['input']
            declaration = {key: body[key] for key in ('response_format', 'text', 'output_config', 'tool_choice', 'tools') if key in body}
            writer.writerow({'id': row['id'], 'protocol': row['protocol'], 'declaration': json.dumps(declaration, ensure_ascii=False),
                             'conversion': row['outcome'], 'kind': constraint.get('kind'), 'schema': constraint.get('schema'),
                             'mapping_decision': mapping.get('decision'), 'candidate_so_args': json.dumps(mapping.get('so_args'), ensure_ascii=False),
                             'transport': 'not attempted', 'sampling': 'not executed', 'instance_validation': 'not executed',
                             'error': json.dumps(row['error'], ensure_ascii=False)})
    return checks


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def provenance():
    package = Path(recipe.__file__).parent
    wheel = PHASE / 'vendor/deepseek_recipe-0.2.0-cp310-abi3-macosx_11_0_arm64.whl'
    paths = [wheel, *package.glob('*.so'), package / '_native.pyi',
             ROOT / 'cpu.py', ROOT / 'test_cpu.py', ROOT / 'cpu-cases.json',
             PHASE / 'vendor/minimal/source-metadata.json', PHASE / 'vendor/exp20-source/sources.json',
             PHASE / 'vendor/exp21-source/sources.json']
    files = [{'path': str(p.resolve()), 'bytes': p.stat().st_size,
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    source_manifest = json.loads((PHASE / 'vendor/exp21-source/sources.json').read_text())
    source_verification = []
    for entry in source_manifest['files']:
        if 'local_path' not in entry:
            continue
        source = (PHASE.parent / entry['local_path']).resolve()
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
        match = digest == entry['sha256'] and blob == entry['git_blob_sha1']
        source_verification.append({'path': str(source), 'sha256': digest, 'git_blob_sha1': blob,
                                    'recorded_hashes_match': match, 'git_tree_match': entry.get('git_tree_match')})
        if not match:
            raise ValueError(f'Source hash mismatch: {source}')
    with zipfile.ZipFile(wheel) as archive:
        native = next(p for p in paths if p.suffix == '.so')
        member = next(n for n in archive.namelist() if n.endswith('/' + native.name))
        wheel_native_sha = hashlib.sha256(archive.read(member)).hexdigest()
    return {'utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
            'executable': sys.executable, 'platform': platform.platform(),
            'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
            'recipe_version': recipe.__version__, 'recipe_source_commit': RECIPE_COMMIT,
            'deepinfer_source_commit': DEEPINFER_COMMIT, 'files': files, 'source_verification': source_verification,
            'installed_native_matches_wheel': wheel_native_sha == hashlib.sha256(native.read_bytes()).hexdigest(),
            'installed_stub_matches_fixed_source': (package / '_native.pyi').read_bytes()
                == (PHASE / 'vendor/exp21-source/deepseek-recipe/deepseek-recipe-python/python/deepseek_recipe/_native.pyi').read_bytes(),
            'native_build_commit': 'not attested; fixed source and matching Python stub do not prove native build revision',
            'dependencies_installed': False, 'gpu_inference': False, 'deepinfer_imported': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PHASE / 'results/exp21/cpu/formal-v1')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to((PHASE / 'results/exp21/cpu').resolve()):
        parser.error('Output must remain inside results/exp21/cpu/')
    out.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads((ROOT / 'cpu-cases.json').read_text())
    cases = fixtures['cases']
    write_json(out / 'environment.json', provenance())
    for name in ['cpu.py', 'test_cpu.py', 'cpu-cases.json']:
        (out / 'provenance').mkdir(exist_ok=True)
        shutil.copyfile(ROOT / name, out / 'provenance' / name)
    shutil.copyfile(PHASE / 'vendor/exp21-source/sources.json', out / 'provenance' / 'sources.json')
    rows = []
    with (out / 'records.jsonl').open('w') as stream:
        for case in cases:
            row = run_case(case)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'); stream.flush()
    # Re-read persisted bytes for the completeness audit.
    persisted = [json.loads(line) for line in (out / 'records.jsonl').read_text().splitlines()]
    summary = summarize(cases, persisted)
    summary['by_protocol'] = {p: summarize([c for c in cases if c['protocol'] == p],
                                         [r for r in persisted if r['protocol'] == p]) for p in REQUEST}
    summary['constraint_kinds'] = dict(Counter(
        (r['snapshot']['output_constraint'] or {}).get('kind', 'none')
        for r in persisted if r['outcome'] == 'accepted'))
    by_id = {case['id']: case for case in cases}
    probes = fixtures.get('parser_probes', {}).get('cases', [])
    with (out / 'parser-probes.jsonl').open('w') as stream:
        for probe in probes:
            row = parse_probe(by_id[probe['conversion_id']], probe['raw'])
            row.update(id=probe['id'], probe_sha256=identity(probe),
                       manual_fixture_truth=probe.get('manual_fixture_truth'))
            row['verdict'] = assess_probe(probe, row)
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'); stream.flush()
    probe_rows = [json.loads(line) for line in (out / 'parser-probes.jsonl').read_text().splitlines()]
    summary['parser_probes'] = {'configured': len(probes), 'recorded': len(probe_rows),
                               'passed': sum(r['verdict'] == 'pass' for r in probe_rows),
                               'failed': sum(r['verdict'] == 'fail' for r in probe_rows),
                               'unknown': sum(r['verdict'] == 'unknown' for r in probe_rows),
                               'scope': 'synthetic backend text through real recipe parser; not model generation or schema validation'}
    summary['ok'] = summary['ok'] and len(probes) == len(probe_rows) and all(
        r['id'] == p['id'] and r['probe_sha256'] == identity(p) and assess_probe(p, r) == 'pass'
        for p, r in zip(probes, probe_rows))
    invariants = export_contracts(out, persisted, probe_rows)
    summary['candidate_invariants'] = {'configured': len(invariants), 'passed': sum(x['status'] == 'pass' for x in invariants)}
    summary['ok'] = summary['ok'] and all(x['status'] == 'pass' for x in invariants)
    write_json(out / 'summary.json', summary)
    write_json(out / 'artifacts-sha256.json', {
        str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'artifacts-sha256.json'})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
