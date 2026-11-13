"""Real recipe conversion/encoding probes, no inference or HTTP service."""
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import deepseek_recipe as recipe
from audit import identity, fact_equal, summarize

ROOT=Path(__file__).resolve().parent
PHASE=ROOT.parent
VERSION={'v41':recipe.ModelVersion.DeepseekV41Flash,'v4':recipe.ModelVersion.DeepseekV4Pro}
ENCODING={'v41':recipe.DeepseekV41Encoding,'v4':recipe.DeepseekV4Encoding}
REQUEST={'chat':recipe.ChatCompletionRequest,'responses':recipe.ResponsesRequest,'messages':recipe.MessagesRequest}
TOKENIZER_SHA256={'v4':'97d2f31b020d18b5aee5c9b3d5b4efb10ea210f3fe3f7dffe3f1cd90542d6b19',
                  'v41':'81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99'}


def verified_tokenizer(path,version):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=TOKENIZER_SHA256[version]:
        raise ValueError(f'{version} tokenizer hash mismatch: {digest}')
    return recipe.Tokenizer.from_file(str(path))


def error(exc,stage):
    return dict(type=type(exc).__name__,message=str(exc),body=getattr(exc,'body',None),
                status_code=getattr(exc,'status_code',None),stage=stage)


def snapshot(request):
    conv=request.conversation;inf=request.inference_options;parse=request.parsing_options
    version=next(k for k,v in VERSION.items() if request.model_version==v)
    messages=[]
    for m in conv.messages:
        messages.append(dict(role=m.role,content=m.content,reasoning_content=m.reasoning_content,
            prefix=m.prefix,tool_call_id=m.tool_call_id,
            tool_calls=None if m.tool_calls is None else [dict(id=t.id,name=t.name,arguments=t.arguments) for t in m.tool_calls],
            image_sources=[dict(kind=i.kind,path=i.path) for i in m.image_sources]))
    tools=[dict(name=t.name,description=t.description,parameters=t.parameters,strict=t.strict,
                defer_loading=t.defer_loading) for t in conv.tools]
    constraint=inf.output_constraint
    return dict(model_version=version,stream=request.stream,
        conversation=dict(messages=messages,thinking_mode=conv.thinking_mode,reasoning_effort=conv.reasoning_effort,
            tools=tools,tool_choice=conv.tool_choice,response_format=conv.response_format,
            response_schema=conv.response_schema,response_regex=conv.response_regex),
        inference_options={**{k:getattr(inf,k) for k in ['max_tokens','temperature','top_p','logprobs','top_logprobs','seed']},
            'output_constraint':None if constraint is None else dict(kind=constraint.kind,schema=constraint.schema)},
        parsing_options={**{k:getattr(parse,k) for k in ['parse_json_output','parse_tool_calls','starts_in_tool_calls','stop_sequences']},
                         'thinking_initial_stage':str(parse.thinking_initial_stage)})


def flat_facts(view):
    c=view['conversation'];i=view['inference_options'];p=view['parsing_options']
    return dict(model_version=view['model_version'],thinking_mode=c['thinking_mode'],reasoning_effort=c['reasoning_effort'],
        roles=[m['role'] for m in c['messages']],message_contents=[m['content'] for m in c['messages']],
        assistant_reasoning_contents=[m['reasoning_content'] for m in c['messages'] if m['role']=='assistant'],
        tool_names=[t['name'] for t in c['tools']],tool_parameter_schemas=[t['parameters'] for t in c['tools']],
        tool_choice=c['tool_choice'],max_tokens=i['max_tokens'],temperature=i['temperature'],top_p=i['top_p'],
        output_constraint_kind=i['output_constraint']['kind'] if i['output_constraint'] else None,
        stop_sequences=p['stop_sequences'],parse_tool_calls=p['parse_tool_calls'],starts_in_tool_calls=p['starts_in_tool_calls'])


def configured(case):
    opt=recipe.ConversionOptions();settings=case.get('options',{})
    if alias:=settings.get('alias'):
        opt=opt.with_model_alias(alias['name'],VERSION[alias['version']])
    mode=settings.get('web_search','default')
    if mode!='default':
        value=recipe.WebSearchBehavior.Reject if mode=='reject' else recipe.WebSearchBehavior.Drop
        method='with_responses_web_search' if case['protocol']=='responses' else 'with_messages_web_search'
        opt=getattr(opt,method)(value)
    return opt


def run_case(case,tokenizers,row=None):
    started=time.perf_counter_ns();checks={};row={} if row is None else row
    row.update(id=case['id'],protocol=case['protocol'],family=case['family'],
        input=case['input'],options=case.get('options',{}),input_sha256=identity(case['input']),
        contract_sha256=identity(case),clock_domain='local_process_perf_counter_ns',conversion={'status':'unknown'},checks=[])
    def check(name,status,evidence):
        checks[name]=dict(name=name,status=status,evidence=evidence)
        row['checks']=list(checks.values())
    def finish():
        for tag in case['checks']:
            if tag not in checks:check(tag,'unknown',{'reason':'check not reached'})
        row['elapsed_ms']=(time.perf_counter_ns()-started)/1e6
        return row
    def outcome(name,fn):
        try:
            ok,evidence=fn();check(name,'pass' if ok else 'fail',evidence)
        except Exception as exc:check(name,'fail',error(exc,name))
    try:
        req=REQUEST[case['protocol']](case['input']).convert(configured(case))
    except Exception as exc:
        row['conversion']={'status':'error','error':error(exc,'request-construction-or-convert')}
        err=row['conversion']['error'];facts={'error_status_code':err['status_code']}
        text=str(exc)+' '+str(err['body']);expected=case['expect']
        check('convert','pass' if expected['conversion']=='error' else 'fail',row['conversion'])
        expected_facts=expected.get('facts',{})
        if 'assert_conversion_error' in case['checks']:
            want=expected_facts.get('error_contains',[])
            ok=all(w in text for w in want) and all(fact_equal(facts.get(k),v) for k,v in expected_facts.items() if k!='error_contains')
            check('assert_conversion_error','pass' if ok else 'fail',{'actual':err,'expected':expected_facts})
        return finish()
    row['conversion']={'status':'ok'}
    check('convert','pass' if case['expect']['conversion']=='ok' else 'fail',{'accepted':True})
    try:
        view=snapshot(req);facts=flat_facts(view);row.update(converted=view,facts=facts)
    except Exception as exc:
        row['observation_error']=error(exc,'snapshot')
        for tag in case['checks']:
            if tag!='convert':check(tag,'fail' if tag=='assert_facts' else 'unknown',row['observation_error'])
        return finish()
    expected={k:v for k,v in case['expect'].get('facts',{}).items() if k!='special_control_counts'}
    differences={k:{'actual':facts.get(k),'expected':v} for k,v in expected.items() if k not in facts or not fact_equal(facts[k],v)}
    check('assert_facts','pass' if not differences else 'fail',differences)
    version=view['model_version'];encoding=ENCODING[version]();rendered=None;ids=None
    try:
        rendered=encoding.render_conversation(req.conversation)
        row['rendered']=dict(prompt=rendered.prompt,special_ranges=rendered.special_ranges,
            range_unit='Python Unicode code point half-open index',
            special_spellings=[rendered.prompt[a:b] for a,b in rendered.special_ranges])
        missing=[t for t in case['expect'].get('contains_text',[]) if t not in rendered.prompt]
        check('render','pass' if not missing else 'fail',{'missing_text':missing})
    except Exception as exc:check('render','fail',error(exc,'render'))
    if 'encode_without_tokenizer_raises_runtime_error' in case['checks']:
        try:
            encoding.encode(req.conversation)
            check('encode_without_tokenizer_raises_runtime_error','fail','no exception')
        except Exception as exc:
            check('encode_without_tokenizer_raises_runtime_error',
                'pass' if isinstance(exc,RuntimeError) and 'no tokenizer' in str(exc) else 'fail',error(exc,'encode_without_tokenizer'))
    if version in tokenizers:
        try:
            ids=encoding.with_tokenizer(tokenizers[version]).encode(req.conversation)
            row['encoding']=dict(status='ok',token_ids=ids,prompt_tokens=len(ids),token_ids_sha256=identity(ids))
            check('encode_with_matching_tokenizer','pass' if ids else 'fail',{'prompt_tokens':len(ids)})
        except Exception as exc:
            row['encoding']=dict(status='error',error=error(exc,'encode'))
            check('encode_with_matching_tokenizer','fail',row['encoding'])
    else:
        row['encoding']={'status':'unknown','reason':'matching tokenizer unavailable'}
        check('encode_with_matching_tokenizer','unknown',row['encoding'])
    # These aliases are separately declared fixture assertions over the real conversion facts.
    aliases={'historical_reasoning_cleared','reasoning_join_protocol_difference','tool_declaration_only',
             'stop_sequences_preserved','unknown_stop_field_ignored','max_tokens_clamped','alias_resolves_version','web_search_dropped'}
    for tag in aliases.intersection(case['checks']):
        check(tag,'pass' if not differences else 'fail',{'facts':facts,'differences':differences})
    if ids is not None:
        P=len(ids);limits=[]
        def resolve(prompt,context):
            try:
                value=req.resolve_max_tokens(prompt,context);limits.append(dict(prompt=prompt,context=context,value=value))
                return value
            except Exception as exc:
                limits.append(dict(prompt=prompt,context=context,error=error(exc,'resolve_max_tokens')));raise
        def refused(context):
            try:resolve(P,context);return False,{'unexpected_accept':limits[-1]}
            except recipe.ConversionError as exc:return exc.status_code==400 and 'maximum context length' in (str(exc)+' '+exc.body),limits[-1]
        defaults={'resolve_default_thinking_65536':65536,'resolve_default_non_thinking_8192':8192,'resolve_default_max_effort_131072':131072}
        for tag,want in defaults.items():
            if tag in case['checks']:
                def probe(w=want):
                    a,b=resolve(P,P+262144),resolve(P,P+7)
                    return a==w and b==7,{'large_context':a,'seven_left':b,'expected_default':w}
                outcome(tag,probe)
        if 'resolve_explicit_max_tokens' in case['checks']:
            M=facts['max_tokens'];outcome('resolve_explicit_max_tokens',lambda:(resolve(P,P+M)==M,{'expected':M}))
        if 'resolve_context_prompt_overflow' in case['checks']:
            outcome('resolve_context_prompt_overflow',lambda:refused(P-1))
        if 'resolve_context_requested_output_overflow' in case['checks']:
            outcome('resolve_context_requested_output_overflow',lambda:refused(P+facts['max_tokens']-1))
        if 'resolve_context_at_limit_returns_one' in case['checks']:
            outcome('resolve_context_at_limit_returns_one',lambda:(resolve(P,P)==1,{'remaining':0,'note':'library boundary behavior, not model generation proof'}))
        row['context_probes']=limits
        if 'literal_special_ranges_excluded' in case['checks'] and rendered is not None:
            def literal_probe():
                text=case['expect']['contains_text'][0];a=rendered.prompt.index(text);b=a+len(text)
                overlap=[r for r in rendered.special_ranges if r[0]<b and r[1]>a]
                return not overlap,{'literal_span':[a,b],'overlapping_control_ranges':overlap}
            outcome('literal_special_ranges_excluded',literal_probe)
        if 'literal_control_token_counts' in case['checks'] and rendered is not None:
            try:
                token=next(iter(case['expect']['facts']['special_control_counts']));control=tokenizers[version].encode(token)
                full=tokenizers[version].encode(rendered.prompt);count=ids.count(control[0]) if len(control)==1 else None
                row['literal_special_probe']=dict(spelling=token,control_id=control,prompt_encoding_count=count,
                    full_vocabulary_count=full.count(control[0]) if len(control)==1 else None,full_vocabulary_ids=full)
                want=case['expect']['facts']['special_control_counts'][token]
                check('literal_control_token_counts','pass' if count==want['prompt_encoding'] else 'fail',row['literal_special_probe'])
                check('full_vocabulary_encoding_differs','pass' if full!=ids and row['literal_special_probe']['full_vocabulary_count']==want['full_vocabulary'] else 'fail',row['literal_special_probe'])
            except Exception as exc:
                for tag in ['literal_control_token_counts','full_vocabulary_encoding_differs']:check(tag,'fail',error(exc,tag))
    for tag in case['checks']:
        if tag not in checks:
            check(tag,'unknown',{'reason':'cross-fixture check pending' if tag=='family_compare' else 'prerequisite unavailable'})
    return finish()


def compare_families(cases,rows):
    groups=defaultdict(list);by_id={c['id']:c for c in cases};reports=[]
    for row in rows:
        if 'family_compare' in by_id[row['id']]['checks']:groups[row['family']].append(row)
    for name,group in groups.items():
        expected=[by_id[r['id']]['expect'].get('facts',{}) for r in group]
        common=set.intersection(*(set(e) for e in expected))
        invariant=[k for k in sorted(common) if k!='special_control_counts' and all(fact_equal(e[k],expected[0][k]) for e in expected)]
        differences={k:[r.get('facts',{}).get(k) for r in group] for k in sorted(common) if k not in invariant}
        expected_n=sum(c['family']==name and 'family_compare' in c['checks'] for c in cases)
        ok=len(group)==expected_n and len(group)>=2 and all(r.get('conversion',{}).get('status')=='ok' and all(k in r.get('facts',{}) and fact_equal(r['facts'][k],by_id[r['id']]['expect']['facts'][k]) for k in invariant) for r in group)
        report=dict(family=name,n=len(group),expected_n=expected_n,ids=[r['id'] for r in group],invariant_fields=invariant,
                    declared_protocol_differences=differences,passed=ok,prompt_equality_required=False)
        reports.append(report)
        for row in group:
            target=next((c for c in row['checks'] if c['name']=='family_compare'),None)
            if target is None:
                target={'name':'family_compare'};row['checks'].append(target)
            target.update(status='pass' if ok else 'fail',evidence=report)
    return reports


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--tokenizer-root',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    provenance=args.out/'provenance';provenance.mkdir()
    for p in [ROOT/'run.py',ROOT/'audit.py',ROOT/'cases.json']:shutil.copyfile(p,provenance/p.name)
    cases=json.loads((ROOT/'cases.json').read_text())['cases'];tokenizers={};meta={}
    for version in VERSION:
        p=args.tokenizer_root/version/'tokenizer.json'
        if p.exists():
            meta[version]=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,expected_sha256=TOKENIZER_SHA256[version])
            try:
                tokenizers[version]=verified_tokenizer(p,version);meta[version]['status']='verified'
            except Exception as exc:meta[version].update(status='invalid',error=error(exc,'tokenizer_preflight'))
        else:meta[version]={'path':str(p),'status':'missing'}
    rows=[]
    for case in cases:
        row={}
        try:rows.append(run_case(case,tokenizers,row))
        except Exception as exc:
            row.update(observation_error=error(exc,'unexpected_observation_failure'))
            found={v['name'] for v in row.get('checks',[])}
            row.setdefault('conversion',{'status':'unknown'});row.setdefault('checks',[])
            row['checks'].extend(dict(name=tag,status='unknown',evidence='observation failed') for tag in case['checks'] if tag not in found)
            rows.append(row)
    families=compare_families(cases,rows)
    for row in rows:(args.out/(row['id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
    summary=summarize(cases,rows);summary.update(families=families,scope='actual native recipe library on CPU; no model/HTTP/tool execution',
        model_inference_calls=0,fixture_sha256=hashlib.sha256((ROOT/'cases.json').read_bytes()).hexdigest(),
        tokenizer=meta,environment={'python':sys.version,'platform':platform.platform(),'package':importlib.metadata.version('deepseek-recipe'),
        'native_module':str(Path(recipe.__file__).parent)},clock_note='local perf_counter elapsed is diagnostic, not inference TTFT',
        code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(provenance.iterdir())})
    (args.out/'records.json').write_text(json.dumps({'records':rows},ensure_ascii=False,indent=2)+'\n')
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['families','outcomes','tokenizer']},ensure_ascii=False))
    if summary['failed'] or summary['unknown']:raise SystemExit(1)


if __name__=='__main__':main()
