#!/usr/bin/env python3
"""Bounded real image API validation. No automatic retries or service changes."""
from pathlib import Path
from datetime import datetime, timezone
from io import BytesIO
import argparse
import base64
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from PIL import Image

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
CONFIG = Path.home()/'.config/qwen-image-kaggle/access.json'
PROMPT = 'A single red cube centered on a plain white background, simple clean illustration, no text.'
PAYLOAD = dict(model='qwen-image-2.1',prompt=PROMPT,size='512x512',n=1,
               steps=8,seed=20261109,response_format='b64_json')
MAX_BODY = 16*1024*1024
SAFE_HEADERS = {'content-type','content-length','date','server','x-request-id',
                'x-correlation-id','retry-after'}

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check_endpoint(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or
        not parsed.hostname.endswith('.gradio.live') or parsed.username or
        parsed.password or parsed.query or parsed.fragment or parsed.port not in (None,443)):
        raise ValueError('Expected a plain HTTPS Gradio share origin; refusing credential transmission')
    if parsed.path not in ('','/'):
        raise ValueError('Base URL must not contain an API path')

def validate_image(result, payload, output):
    if result.get('model') != payload['model'] or len(result.get('data',[])) != 1:
        raise ValueError('Unexpected model or image count')
    generation = result.get('generation',{})
    for key in ('size','steps','seed'):
        if generation.get(key) != payload[key]:
            raise ValueError('Generation metadata mismatch: '+key)
    elapsed = generation.get('elapsed_seconds')
    if isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Missing/invalid server-reported elapsed time')
    if result['data'][0].get('revised_prompt') != payload['prompt']:
        raise ValueError('Prompt metadata mismatch')
    start = time.perf_counter()
    raw = base64.b64decode(result['data'][0]['b64_json'],validate=True)
    decoded = time.perf_counter()
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Response is not PNG')
    with Image.open(BytesIO(raw)) as image:
        image.verify()
    with Image.open(BytesIO(raw)) as image:
        image.load()
        if image.format != 'PNG' or image.size != (512,512):
            raise ValueError('Incorrect image format or dimensions')
        mode = image.mode
    checked = time.perf_counter()
    output.write_bytes(raw)
    readback = output.read_bytes()
    if readback != raw:
        raise ValueError('Disk readback differs from response')
    finished = time.perf_counter()
    return dict(bytes=len(raw),size=[512,512],mode=mode,decoded_sha256=digest(raw),
                disk_readback_sha256=digest(readback),strict_base64=True,png_verified_and_loaded=True,
                full_byte_readback_equal=True,decode_seconds=decoded-start,
                image_validation_seconds=checked-decoded,disk_write_readback_seconds=finished-checked,
                server_reported_elapsed_seconds=elapsed,content_quality='not_yet_reviewed')

class Runner:
    def __init__(self, root, access):
        self.root, self.access = root, access
        self.opener = urllib.request.build_opener(NoRedirect())
        self.rows = []

    def request(self, label, endpoint, payload=None, auth='valid'):
        stage = self.root/'requests'/label
        stage.mkdir(parents=True,exist_ok=False)
        body = None if payload is None else json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        request_id = self.root.name+'-'+label
        record = dict(client_request_id=request_id,server_request_id_propagation='unverified',
                      method='GET' if body is None else 'POST',path=endpoint,auth_mode=auth,
                      started_at=now(),http_dispatch_attempted=False,
                      runner_sha256=digest(Path(__file__).read_bytes()),
                      client_environment_file=getattr(self,'client_environment_file',None),
                      request_body_sha256=None if body is None else digest(body))
        if body is not None:
            (stage/'request-body.json').write_bytes(body)
        write_json(stage/'request.json',record)
        headers = {'Content-Type':'application/json','User-Agent':'p5-exp28/1.0','X-Request-ID':request_id}
        if auth != 'missing':
            headers['Authorization'] = 'Bearer '+(self.access['api_key'] if auth=='valid' else 'p5-deliberately-invalid-key')
        req = urllib.request.Request(self.access['base_url'].rstrip('/')+endpoint,data=body,headers=headers,method=record['method'])
        started = time.perf_counter()
        try:
            record['http_dispatch_attempted']=True
            write_json(stage/'dispatch.json',{'client_request_id':request_id,'at':now(),
                'meaning':'Client started an HTTP dispatch attempt; not proof of server acceptance'})
            try:
                response = self.opener.open(req,timeout=180)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                headers_at = time.perf_counter()
                raw = response.read(MAX_BODY+1)
                finished = time.perf_counter()
                if len(raw)>MAX_BODY:
                    raise ValueError('Response exceeds the bounded capture limit')
                try:
                    parsed = json.loads(raw)
                except (ValueError,UnicodeDecodeError):
                    parsed = None
                if (self.access['api_key'].encode() in raw or
                    (parsed is not None and self.access['api_key'] in json.dumps(parsed,ensure_ascii=False))):
                    raise ValueError('Credential found in response; body not persisted')
                record.update(status=response.code,response_headers={k:v.replace(self.access['api_key'],'[REDACTED]') for k,v in response.headers.items() if k.lower() in SAFE_HEADERS},
                              response_body_sha256=digest(raw),response_bytes=len(raw),
                              client_seconds_to_response_headers=headers_at-started,
                              client_response_read_seconds=finished-headers_at,
                              client_total_http_seconds=finished-started)
                (stage/'response-body.raw').write_bytes(raw)
                if parsed is not None:
                    write_json(stage/'response.json',parsed)
        except Exception as error:
            message = str(error).replace(self.access['api_key'],'[REDACTED]')
            record.update(status=None,error_type=type(error).__name__,error=message,
                          client_total_http_seconds=time.perf_counter()-started,
                          backend_execution_after_failure='unknown; no automatic retry')
            parsed = None
        record['finished_at'] = now()
        write_json(stage/'response-metadata.json',record)
        self.rows.append(record)
        print(json.dumps({k:record.get(k) for k in ('client_request_id','status','client_total_http_seconds','error_type')},ensure_ascii=False),flush=True)
        return record, parsed, stage

    def finish(self, state, reason, image=None):
        summary = dict(run_id=self.root.name,finished_at=now(),state=state,reason=reason,
            request_scope='this invocation; older probes remain on disk and in summary-history',
            requests=self.rows,planned_contract_requests=4,planned_generations=1,
            valid_generation_dispatch_reserved=max(read_state(self.root).get('valid_generation_dispatch_reserved',0),read_state(self.root).get('valid_generation_submitted',0)),
            image_endpoint_http_dispatch_attempts=sum(r.get('http_dispatch_attempted',False) and r['path']=='/v1/images/generations' for r in self.rows),
            valid_generation_http_dispatch_attempts=sum(r.get('http_dispatch_attempted',False) and r['client_request_id'].endswith('R04-real-image') for r in self.rows),
            successful_images_received=int(image is not None),backend_gpu_attempts=None,
            backend_execution_log_received=False,full_provenance_accepted=False,
            api_contract_and_delivery_passed=state=='api_validated',image=image,
            timing_boundaries={'client_http':'dispatch through complete response body; not TTFT',
              'client_headers':'time to HTTP response headers, not first image/model token',
              'server_elapsed':'self-reported; observed implementation starts before generation lock and includes image/file processing',
              'queue_seconds':None,'pipeline_only_seconds':None,'network_only_seconds':None,
              'cold_start_or_model_load_measured':False},
            unsupported_claims=['token usage','TTFT','SSE','KV/prefix cache','continuous batching',
                                'capacity or HA','CUDA cancellation','currency cost'],
            automatic_retries=False,service_restarted=False,existing_models_replaced=False)
        previous=self.root/'summary.json'
        if previous.exists():
            old=previous.read_bytes()
            history=self.root/'summary-history'; history.mkdir(exist_ok=True)
            (history/(digest(old)+'.json')).write_bytes(old)
        write_json(self.root/'summary.json',summary)
        return summary

def read_state(root):
    p=root/'dispatch-state.json'
    return json.loads(p.read_text()) if p.exists() else {}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--execute',action='store_true',help='After a healthy preflight, send 4 serial cases, at most one valid generation')
    args=parser.parse_args()
    root=(args.run_dir or BASE/'phase5/results/exp28'/('exp28-kaggle-20261109-'+uuid.uuid4().hex[:8])).resolve()
    root.mkdir(parents=True,exist_ok=True)
    if read_state(root).get('valid_generation_submitted',0) or read_state(root).get('valid_generation_dispatch_reserved',0):
        raise SystemExit('A generation was already submitted for this run; refusing retry or duplicate')
    if stat.S_IMODE(args.config.stat().st_mode)!=0o600:
        raise SystemExit('Private config must have mode 0600')
    access=json.loads(args.config.read_text())
    check_endpoint(access['base_url'])
    if not isinstance(access.get('api_key'),str) or len(access['api_key'])<16:
        raise SystemExit('Invalid private credential configuration')
    code=Path(__file__).read_bytes()
    code_dir=root/'code-snapshots'; code_dir.mkdir(exist_ok=True)
    (code_dir/(digest(code)+'.py')).write_bytes(code)
    environment_file=root/('client-environment.json' if not (root/'client-environment.json').exists() else 'client-environment-'+uuid.uuid4().hex[:8]+'.json')
    write_json(environment_file,{'observed_at':now(),'python':platform.python_version(),
        'platform':platform.platform(),'Pillow':importlib.metadata.version('Pillow'),
        'python_executable':os.sys.executable,'runner_sha256':digest(code),'credential_mode':'0600',
        'endpoint_origin':access['base_url'],'automatic_retries':False})
    runner=Runner(root,access)
    runner.client_environment_file=environment_file.name
    row, health, _ = runner.request('preflight-'+uuid.uuid4().hex[:8],'/health')
    if row['status']!=200 or not isinstance(health,dict) or health.get('ready') is not True:
        runner.finish('preflight_unavailable','No generation sent: health unavailable or not ready')
        return 75
    if not args.execute:
        runner.finish('preflight_ready','Read-only preflight completed; generation was not requested')
        return 0
    cases=[('R01-missing-auth','missing',PAYLOAD,401),('R02-invalid-auth','invalid',PAYLOAD,401),
           ('R03-invalid-steps','valid',dict(PAYLOAD,steps=7),422),('R04-real-image','valid',PAYLOAD,200)]
    for label, auth, payload, expected in cases:
        if label.startswith('R04'):
            write_json(root/'dispatch-state.json',{'valid_generation_dispatch_reserved':1,'at':now(),
                       'note':'Persisted before dispatch; ambiguous outcomes must not be retried'})
        row,result,stage=runner.request(label,'/v1/images/generations',payload,auth)
        if row['status']!=expected:
            runner.finish('case_failed',label+' returned unexpected status; stopped without retry')
            return 1
        if expected==200:
            try:
                image=validate_image(result,payload,stage/'image.png')
            except Exception as error:
                runner.finish('delivery_failed',str(error))
                return 1
            write_json(stage/'image-readback.json',image)
            runner.finish('api_validated','4 contract cases passed; backend provenance and human quality review remain separate',image)
            return 0

if __name__=='__main__':
    raise SystemExit(main())
