"""Isolated official-source expressions/reference functions; no engine or GPU."""
import argparse
import ast
import dataclasses
import hashlib
import json
from pathlib import Path
import shutil
import sys
import types
import uuid

SOURCE=Path(__file__).resolve().parents[1]/'vendor/exp23-source/DeepInfer'
ENV=SOURCE/'deepinfer/environ.py'
RUNNER=SOURCE/'deepinfer/worker/model_runner.py'
YOCO=SOURCE/'examples/yoco/yoco_equiv.py'


def controlled_environment(config):
    module=types.ModuleType('exp23_env_'+uuid.uuid4().hex)
    exec(compile(ENV.read_text(),str(ENV),'exec'),module.__dict__)
    # The source only declares descriptors at import; resolving them reads this map.
    module.os=types.SimpleNamespace(getenv=config.get)
    return module


def guard_ast():
    tree=ast.parse(RUNNER.read_text())
    method=next(m for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='ModelRunner'
                for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='load_model')
    blocks=[b for b in method.body if isinstance(b,ast.If) and
            ast.unparse(b.test)=="self.yoco_prefill_truncation_mode != 'off'"]
    if len(blocks)!=1:raise ValueError('source guard identity changed')
    return ast.Module(body=blocks,type_ignores=[])


def probe_config(config,window):
    module=controlled_environment(config);record={'provided_config':config.copy(),'window':window}
    try:
        env=module.envs
        record.update(nextn=env.DEEPINFER_USE_NEXTN_DECODE,backtracking=env.DEEPINFER_MAX_BACKTRACKING_TOKENS,
                      mode=env.DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE,keep=env.DEEPINFER_YOCO_PREFILL_KEEP_TOKENS)
    except (ValueError,TypeError) as error:
        return {**record,'status':'parse_rejected','error_type':type(error).__name__}
    try:
        self=types.SimpleNamespace(window_size=window,yoco_prefill_truncation_mode=record['mode'])
        exec(compile(guard_ast(),str(RUNNER),'exec',optimize=0),{'self':self,'envs':env})
        record['status']='guard_passed'
    except AssertionError:record['status']='guard_rejected'
    return record


def reference_namespace():
    wanted={'SeqSpec','MaskCase','build_mask_cases','_reference_visible','_expand_pivots'}
    nodes=[n for n in ast.parse(YOCO.read_text()).body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in wanted]
    if {n.name for n in nodes}!=wanted:raise ValueError('source reference identity changed')
    module=types.ModuleType('exp23_yoco_'+uuid.uuid4().hex);module.dataclass=dataclasses.dataclass
    sys.modules[module.__name__]=module
    try:exec(compile(ast.Module(body=nodes,type_ignores=[]),str(YOCO),'exec'),module.__dict__)
    finally:sys.modules.pop(module.__name__,None)
    return module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    specs=[]
    def add(name,mode='compact',keep='140',nextn=None,raw=None,window=128,expected='guard_passed'):
        config={'DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE':mode,'DEEPINFER_YOCO_PREFILL_KEEP_TOKENS':keep}
        if nextn is not None:config['DEEPINFER_USE_NEXTN_DECODE']=nextn
        if raw is not None:config['DEEPINFER_MAX_BACKTRACKING_TOKENS']=raw
        specs.append({'id':name,'config':config,'window':window,'expected':expected})
    specs.append({'id':'defaults_off','config':{},'window':128,'expected':'guard_passed'})
    add('below_default_bound',keep='133',expected='guard_rejected')
    add('at_default_bound',keep='134');add('mask_at_bound',mode='mask',keep='134');add('recommended140')
    add('zero_draft_below',nextn='0',keep='128',expected='guard_rejected');add('zero_draft_at',nextn='0',keep='129')
    add('explicit_backtrack_below',raw='20',keep='147',expected='guard_rejected');add('explicit_backtrack_at',raw='20',keep='148')
    add('negative_raw_clamped',raw='-1',keep='134');add('no_window',window=0,expected='guard_rejected')
    add('zero_keep',keep='0',expected='guard_rejected');add('invalid_mode',mode='invalid',expected='parse_rejected')
    add('invalid_keep',keep='invalid',expected='parse_rejected');add('invalid_nextn',nextn='invalid',expected='parse_rejected')
    add('invalid_backtrack',raw='invalid',expected='parse_rejected')
    plan={'scope':'isolated official configuration parser, AST guard and Python reference functions; no engine/C++ extension/metadata kernel/model inference',
          'config_specs':specs,'mask_reference_args':{'keep_tokens':140,'window':128,'chunk':512},
          'reference_limit':'_reference_visible does not include swa_valid_start; no general metadata equivalence claim',
          'source_sha256':{str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ENV,RUNNER,YOCO]},
          'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    provenance=out/'provenance';provenance.mkdir();shutil.copyfile(__file__,provenance/'source_probes.py')
    results=[]
    for spec in specs:
        r=probe_config(spec['config'],spec['window']);results.append({'id':spec['id'],**r,'expected':spec['expected'],'conformant':r['status']==spec['expected']})
    module=reference_namespace();visibility=[]
    for case in module.build_mask_cases(**plan['mask_reference_args']):
        for i,spec in enumerate(case.seqs):
            for pos in range(spec.q_start,spec.q_start+spec.q_len):
                visible=module._reference_visible(spec,pos,140,128)
                # Independent finite-set intersection for this reference-only path.
                expected=sorted(set(range(max(0,pos-127),pos+1)).intersection(range(max(0,spec.N-140),spec.N)))
                visibility.append({'case':case.name,'sequence':i,'position':pos,'count':len(visible),
                                   'first':visible[0] if visible else None,'last':visible[-1] if visible else None,
                                   'conformant':visible==expected})
    spec=module.SeqSpec(2000,1900,100)
    pivot_cases=[{'row':[1100,2,2003,2],'sec1_start':1000,'sec2_start':2000,'base':1900,'expected':[1872,1873,1903,1904]},
                 {'row':[1100,2,2003,2],'sec1_start':1000,'sec2_start':2000,'base':1960,'expected':[1872,1873,1963,1964]},
                 {'row':[0,0,0,0],'sec1_start':1000,'sec2_start':2000,'base':1900,'expected':[]}]
    for case in pivot_cases:
        case['actual']=module._expand_pivots(case['row'],case['sec1_start'],case['sec2_start'],spec,128,case['base'])
        case['conformant']=case['actual']==case['expected']
    config={'DEEPINFER_USE_NEXTN_DECODE':'5'};envmodule=controlled_environment(config)
    observed=[(envmodule.envs.DEEPINFER_USE_NEXTN_DECODE,envmodule.envs.DEEPINFER_MAX_BACKTRACKING_TOKENS)]
    config['DEEPINFER_USE_NEXTN_DECODE']='0'
    observed.append((envmodule.envs.DEEPINFER_USE_NEXTN_DECODE,envmodule.envs.DEEPINFER_MAX_BACKTRACKING_TOKENS))
    envmodule.rearm_all();observed.append((envmodule.envs.DEEPINFER_USE_NEXTN_DECODE,envmodule.envs.DEEPINFER_MAX_BACKTRACKING_TOKENS))
    cache={'observed':observed,'conformant':observed==[(5,6),(5,6),(0,1)]}
    (out/'config-records.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    (out/'reference-visible.json').write_text(json.dumps(visibility,ensure_ascii=False,indent=2)+'\n')
    (out/'pivot-reference.json').write_text(json.dumps(pivot_cases,ensure_ascii=False,indent=2)+'\n')
    (out/'cache-control.json').write_text(json.dumps(cache,ensure_ascii=False,indent=2)+'\n')
    summary={'scope':plan['scope'],'configs':len(results),'guard_passed':sum(r['status']=='guard_passed' for r in results),
             'guard_rejected':sum(r['status']=='guard_rejected' for r in results),'parse_rejected':sum(r['status']=='parse_rejected' for r in results),
             'config_conformant':sum(r['conformant'] for r in results),'reference_shape_cases':10,'reference_rows':len(visibility),
             'reference_rows_conformant':sum(r['conformant'] for r in visibility),'pivot_cases':len(pivot_cases),
             'pivot_conformant':sum(r['conformant'] for r in pivot_cases),'cache_control_passed':cache['conformant']}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary))
    if any(not r['conformant'] for r in results+visibility+pivot_cases) or not cache['conformant']:raise SystemExit(1)


if __name__=='__main__':main()
