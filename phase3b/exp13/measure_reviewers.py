#!/usr/bin/env python3
"""DARYU CPU/CUDA 实测；不启动服务，结果保存 device/dtype/原始判定。
CUDA_VISIBLE_DEVICES='' /root/vllm-env/bin/python measure_reviewers.py --out reviewers.json
"""
import argparse, gc, json, os, platform, time
from pathlib import Path
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
import torch
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',required=True); ap.add_argument('--threads',type=int,default=4); ap.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    args=ap.parse_args(); torch.set_num_threads(args.threads)
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
    device=args.device; dtype=torch.bfloat16 if device=='cuda' else torch.float32
    def sync():
        if device=='cuda':torch.cuda.synchronize()
    dataset=json.loads((Path(__file__).parent/'cases.json').read_text())
    texts=[x['text'] for x in dataset['cases']]
    out={'device':device,'dtype':str(dtype),'gpu_name':torch.cuda.get_device_name() if device=='cuda' else None,'torch':torch.__version__,'threads':args.threads,
         'platform':platform.platform(),'policy':dataset['policy'],'cases':dataset['cases'],
         'measurement':'isolated reviewer calls; CUDA synchronized when applicable; excludes model load',
         'latency_scope':{'embedding_ms':'tokenization + forward + pooling; excludes model load',
                          'classifier_ms':'generate including prompt prefill and output; excludes tokenization and model load'}}
    t0=time.perf_counter()
    directory='/opt/models/Qwen3-Embedding-0.6B'
    tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True)
    model=AutoModel.from_pretrained(directory,local_files_only=True,torch_dtype=dtype).to(device).eval()
    def embed(text):
        batch=tokenizer([text],return_tensors='pt',padding=True,truncation=True,max_length=256).to(device)
        with torch.inference_mode():
            hidden=model(**batch).last_hidden_state
            v=hidden[torch.arange(hidden.shape[0],device=device), batch['attention_mask'].sum(1)-1]
            return torch.nn.functional.normalize(v.float(),p=2,dim=1)[0]
    refs=torch.stack([embed(x) for x in dataset['references']])
    out['embedding_load_s']=time.perf_counter()-t0
    out['embedding']=[]
    for repeat in range(3):
        for i,text in enumerate(texts):
            sync(); begin=time.perf_counter(); vec=embed(text); score=float((refs@vec).max().clamp(-1,1)); sync()
            out['embedding'].append({'id':dataset['cases'][i]['id'],'repeat':repeat,'score':score,'ms':(time.perf_counter()-begin)*1000})
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print('embedding measured',flush=True)
    del model,tokenizer,refs;gc.collect()
    if device=='cuda':torch.cuda.empty_cache()
    t0=time.perf_counter();directory='/opt/models/Qwen3-0.6B'
    tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(directory,local_files_only=True,torch_dtype=dtype).to(device).eval()
    out['classifier_load_s']=time.perf_counter()-t0;out['classifier']=[]
    for repeat in range(2):
        for case in dataset['cases']:
            messages=[{'role':'system','content':'你是句子分类器。规则：'+dataset['policy']+' 仅回答 BLOCK 或 ALLOW，不要解释。'},
                      {'role':'user','content':case['text']}]
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
            batch=tokenizer(prompt,return_tensors='pt').to(device);sync();begin=time.perf_counter()
            with torch.inference_mode():
                ids=model.generate(**batch,max_new_tokens=6,do_sample=False,temperature=1.0,top_p=1.0,top_k=0,pad_token_id=tokenizer.eos_token_id)
            sync();ms=(time.perf_counter()-begin)*1000
            answer=tokenizer.decode(ids[0,batch['input_ids'].shape[1]:],skip_special_tokens=True).strip()
            verdict=answer if answer in ('BLOCK','ALLOW') else 'INVALID'
            out['classifier'].append({'id':case['id'],'repeat':repeat,'answer':answer,'verdict':verdict,'ms':ms,
                                      'input_tokens':batch['input_ids'].shape[1],
                                      'output_tokens':ids.shape[1]-batch['input_ids'].shape[1]})
        Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2));print('classifier repeat',repeat,flush=True)
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2));print(args.out,flush=True)

if __name__=='__main__':main()
