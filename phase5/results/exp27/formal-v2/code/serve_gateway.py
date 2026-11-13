import argparse,json,os,pathlib
import uvicorn
from transformers import AutoTokenizer
from gateway import Gateway,sha
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--model',default='/opt/models/Qwen3-0.6B');a=p.parse_args();out=pathlib.Path(a.out)
 plan=json.loads((out/'plan.json').read_text());tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True)
 identity={**plan['identity'],'template_sha256':sha(tok.chat_template.encode())}
 app=Gateway(plan,encoder=lambda m:tok.apply_chat_template(m,tokenize=True,add_generation_prompt=True,enable_thinking=False),log_path=out/'gateway.jsonl',identity=identity)
 (out/'gateway-startup.json').write_text(json.dumps({'pid':os.getpid(),'clock_domain':app.clock_domain,'plan_sha256':sha((out/'plan.json').read_bytes()),'identity':identity,'source_sha256':{x.name:sha(x.read_bytes()) for x in pathlib.Path(__file__).parent.glob('*.py')}},indent=2)+'\n')
 uvicorn.run(app,host='127.0.0.1',port=plan['gateway_port'],log_level='warning',lifespan='off')
