"""Actual constraint-channel controls; schema is absent from prompt text."""
import argparse,json,urllib.request,urllib.error
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    schema={'type':'object','properties':{'flag':{'type':'string','enum':['CONSTRAINED21']}},'required':['flag'],'additionalProperties':False}
    rows=[]
    for name,extra in [('prompt_only',{}),('json_object',{'response_format':{'type':'json_object'}}),('schema_control',{'response_format':{'type':'json_schema','json_schema':{'name':'control','strict':True,'schema':schema}}}),('invalid_schema',{'response_format':{'type':'json_schema','json_schema':{'name':'invalid','schema':{'type':'invented'}}}})]:
        body={'model':a.model,'messages':[{'role':'user','content':'只输出单词FREE，不要输出其他内容。'}],'temperature':0,'max_tokens':128,'chat_template_kwargs':{'enable_thinking':False},**extra}
        row={'id':name,'payload':body}
        req=urllib.request.Request(a.base_url.rstrip('/')+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Exp21-Run':'preflight-exp21','X-Exp21-ID':'probe-'+name})
        try:
            with urllib.request.urlopen(req,timeout=120) as r:row.update(status=r.status,response=json.loads(r.read()))
        except urllib.error.HTTPError as e:row.update(status=e.code,error=e.read().decode())
        except Exception as e:row['transport_error']=str(e)
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    a.out.write_text(json.dumps({'scope':'GPU preflight controls, separate from formal dataset','records':rows},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
