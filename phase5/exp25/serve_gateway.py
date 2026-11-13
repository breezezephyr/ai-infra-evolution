"""Wire the tested gateway to one fixed local model/tokenizer and HTTP backend."""
import argparse,json,pathlib,hashlib,os,sys
import uvicorn
from transformers import AutoTokenizer
from gateway import Config,HTTPBackend,create_app,sha

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--port',type=int,default=8125);ap.add_argument('--backend',default='http://127.0.0.1:8025');ap.add_argument('--model',default='/opt/models/Qwen3-0.6B');a=ap.parse_args()
 out=pathlib.Path(a.out);out.mkdir(exist_ok=True,parents=True)
 tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True)
 ids=json.loads(pathlib.Path('/opt/exp25-20261026-p5g/model-identity.json').read_text())
 identity={'model_fingerprint':ids['files']['model.safetensors'],'model_revision':ids['model_revision'],
  'tokenizer_fingerprint':ids['files']['tokenizer.json'],'template_sha256':sha(tok.chat_template.encode()),
  'backend':'vllm0.8.5-qwen3-0.6b-bf16-native-no-thinking'}
 cfg=Config(log_path=out/'gateway.jsonl',identity=identity)
 app=create_app(cfg,HTTPBackend(a.backend),lambda messages:tok.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
 sources={x.name:sha(x.read_bytes()) for x in pathlib.Path(__file__).parent.glob('*.py')}
 (out/'gateway-startup.json').write_text(json.dumps({'pid':os.getpid(),'port':a.port,'backend':a.backend,'identity':identity,
  'source_sha256':sources,'code_directory':str(pathlib.Path(__file__).parent.resolve()),'active_limit':1,'queue_limit':1,
  'prompt_limit':512,'full_response_gate':True,'semantic_cache_enabled':False,'clock_domain':app.state.gateway.clock_domain},indent=2)+'\n')
 uvicorn.run(app,host='127.0.0.1',port=a.port,log_level='warning')
