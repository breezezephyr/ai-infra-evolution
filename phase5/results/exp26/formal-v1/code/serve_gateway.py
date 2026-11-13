import argparse,json,os,pathlib
import uvicorn
from gateway import Gateway,sha
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=pathlib.Path(a.out)
 plan=json.loads((out/'plan.json').read_text())
 app=Gateway(plan['cases'],out/'gateway.jsonl',f'http://127.0.0.1:{plan["backend_port"]}')
 (out/'gateway-startup.json').write_text(json.dumps({'pid':os.getpid(),'port':plan['gateway_port'],'clock_domain':app.clock_domain,'plan_sha256':sha((out/'plan.json').read_bytes()),'source_sha256':{x.name:sha(x.read_bytes()) for x in pathlib.Path(__file__).parent.glob('*.py')}},indent=2)+'\n')
 uvicorn.run(app,host='127.0.0.1',port=plan['gateway_port'],log_level='warning',lifespan='off')
