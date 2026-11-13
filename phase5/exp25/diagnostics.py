"""Optional historical semantic-score replay; no embeddings or GPU are executed."""
import json,pathlib,hashlib,argparse

def lab_rule(text):return 'LAB_BLOCK' in text

def replay(cases):
 rows=[]
 for c in cases:
  if c['score'] is None:selected=None;outcome='unknown'
  elif c['score']<c['threshold']:selected=None;outcome='rejected'
  else:selected=c['nearest_neighbor_id'];outcome='false_hit' if selected!=c['label'] else 'correct_hit'
  rows.append({'id':c['id'],'selected':selected,'outcome':outcome,'score':c['score'],'threshold':c['threshold']})
 return {'planned':len(rows),'false_hits':sum(x['outcome']=='false_hit' for x in rows),'unknown':sum(x['outcome']=='unknown' for x in rows),'rejected':sum(x['outcome']=='rejected' for x in rows),'rows':rows}

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--input',default='phase5/results/exp25/preflight/legacy-diagnostics-input.json');ap.add_argument('--out',required=True);ap.add_argument('--enable-semantic-replay',action='store_true');a=ap.parse_args()
 p=pathlib.Path(a.input);d=json.loads(p.read_text());out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 for s in d['sources'].values():assert hashlib.sha256(pathlib.Path(s['source_path']).read_bytes()).hexdigest()==s['sha256']
 report={'scope':'CPU replay of retained historical scores/examples; no new embeddings, classifiers, model calls or real gateway requests',
 'input_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'semantic_enabled':a.enable_semantic_replay,
 'semantic_replay':replay(d['exp11']['scored_false_hit_groups']) if a.enable_semantic_replay else None,
 'query_join_limitation':d['reference_contract']['exp11_join_limitation'],
 'review_live_history':d['exp13']['live_review_examples'],
 'lab_marker_probe':[{'id':x['id'],'expected_blocked':x['label'],'lab_marker_blocked':lab_rule(x['text'])} for x in d['exp13']['live_review_examples']]}
 (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'scope':report['scope'],'semantic_rows':report['semantic_replay']['planned'] if report['semantic_replay'] else 0,'false_hits':report['semantic_replay']['false_hits'] if report['semantic_replay'] else None,'marker_probe_rows':len(report['lab_marker_probe'])},ensure_ascii=False))
