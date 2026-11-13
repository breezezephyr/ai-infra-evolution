"""Record real native-library streams; fixture data never executes tools."""
import hashlib
import json
import deepseek_recipe as recipe

REQUEST={'chat':recipe.ChatCompletionRequest,'responses':recipe.ResponsesRequest,'messages':recipe.MessagesRequest}
RESPONSE={'chat':recipe.ChatCompletionResponse,'responses':recipe.ResponsesResponse,'messages':recipe.MessagesResponse}


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pieces(data,pattern):
    if not data:return []
    if pattern=='whole':return [data]
    sizes=[1] if pattern=='unit' else [1,3,2,5]
    chunks=[];i=0;j=0
    while i<len(data):
        size=sizes[j%len(sizes)];chunks.append(data[i:i+size]);i+=size;j+=1
    return chunks


def request_body(case,protocol):
    body={'model':'DeepSeek-V4.1-Flash','stream':True}
    if protocol=='responses':
        body.update(input='请继续报站',reasoning={'effort':'high' if case['thinking'] else 'none'})
    else:
        body.update(messages=[{'role':'user','content':'请继续报站'}],max_tokens=128,
                    thinking={'type':'enabled' if case['thinking'] else 'disabled'})
    if protocol=='chat':body['stream_options']={'include_usage':True}
    if case.get('tools'):
        params={'type':'object','properties':{'city':{'type':'string'}},'required':['city']}
        if protocol=='chat':body['tools']=[{'type':'function','function':{'name':n,'parameters':params}} for n in case['tools']]
        elif protocol=='responses':body['tools']=[{'type':'function','name':n,'parameters':params} for n in case['tools']]
        else:body['tools']=[{'name':n,'input_schema':params} for n in case['tools']]
    return body


def semantic(protocol,body):
    text='';reasoning='';tools=[];finish=None;status=None;stop=None
    if protocol=='chat':
        choice=body['choices'][0];m=choice['message'];text=m.get('content') or '';reasoning=m.get('reasoning_content') or ''
        tools=[{'id':t['id'],'name':t['function']['name'],'arguments':t['function']['arguments']} for t in m.get('tool_calls',[])]
        finish=choice.get('finish_reason')
    elif protocol=='responses':
        for item in body.get('output',[]):
            if item['type']=='message':text+=''.join(c.get('text','') for c in item.get('content',[]))
            elif item['type']=='reasoning':reasoning+=''.join(c.get('text','') for c in item.get('content',[]))
            elif item['type']=='function_call':tools.append({'id':item['call_id'],'name':item['name'],'arguments':item['arguments']})
        status=body.get('status');finish=(body.get('incomplete_details') or {}).get('reason') or status
    else:
        for item in body.get('content',[]):
            if item['type']=='text':text+=item['text']
            elif item['type']=='thinking':reasoning+=item['thinking']
            elif item['type']=='tool_use':tools.append({'id':item['id'],'name':item['name'],'arguments':item['input']})
        finish=body.get('stop_reason');stop=body.get('stop_sequence')
    for t in tools:
        if isinstance(t['arguments'],str):
            try:t['arguments']=json.loads(t['arguments'])
            except ValueError:pass
    return dict(text=text,reasoning=reasoning,tools=tools,finish=finish,status=status,stop_sequence=stop)


def run_case(case,protocol='chat',mode='text',pattern='whole',tokenizer=None):
    row=dict(fixture=case,protocol=protocol,mode=mode,pattern=pattern,events=[],
             backend_finish_seen=False,native_finished=False,unsubmitted_units=0,
             unexpected_error=None,termination_source='unknown')
    body=request_body(case,protocol);row['request']=body
    req=REQUEST[protocol](body).convert(recipe.ConversionOptions());options=req.parsing_options
    options.stop_sequences=case.get('stop',[])
    row['parsing_settings']={'stop_sequences':options.stop_sequences,'thinking_initial_stage':str(options.thinking_initial_stage)}
    action=case['action'];use_tokenizer=tokenizer if mode in {'tokens','text_tokenizer'} or action=='logprob_mismatch' else None
    if action=='no_tokenizer':use_tokenizer=None
    processor=recipe.StreamProcessor(REQUEST[protocol].chunk_generator(req,'exp20','DeepSeek-V4.1-Flash'),options,use_tokenizer)
    response=RESPONSE[protocol]('exp20','DeepSeek-V4.1-Flash',0,13,3)
    row['usage_sources']={'prompt':'synthetic backend PromptUsage: 13 total, 3 cache hit',
                          'completion':'token IDs' if mode=='tokens' else ('synthetic text token_count' if case.get('text_token_count') else 'unmeasured text token_count=0'),
                          'processor_has_tokenizer':use_tokenizer is not None}
    def emit(outputs):
        for out in outputs:
            row['events'].append({'event':RESPONSE[protocol].sse_event_name(out),'data':out.to_json()})
            response.accumulate(out)
    def push(chunk):
        # Native errors stay distinct from observation/serialization errors.
        try:outputs=processor.push(chunk)
        except Exception as exc:
            row['native_error']={'type':type(exc).__name__,'message':str(exc)};raise
        emit(outputs)
    try:
        push(recipe.InferenceChunk.ready(prompt_usage=recipe.PromptUsage(prompt_tokens=13,prompt_cache_hit_tokens=3)))
        if action=='no_tokenizer':push(recipe.InferenceChunk.tokens([1]))
        elif action=='logprob_mismatch':push(recipe.InferenceChunk.tokens([1,2],[(0.0,[])]))
        else:
            data=tokenizer.encode(case['raw']) if mode=='tokens' else case['raw']
            row['input_units']=data;chunks=pieces(data,pattern);submitted=0
            for part in chunks:
                if processor.finished:break
                push(recipe.InferenceChunk.tokens(part) if mode=='tokens' else recipe.InferenceChunk.text(part,case.get('text_token_count',0)))
                submitted+=len(part)
            row['unsubmitted_units']=len(data)-submitted
            row['native_finished_after_data']=processor.finished
            if processor.finished:row['termination_source']='parser_stop'
            elif action in {'close','close_then_finish'}:
                processor.close();row['termination_source']='client_abort'
            elif action=='eof':
                emit(processor.finish());row['termination_source']='unconfirmed_eof'
            else:
                reason=action if action in {'Stop','Length','ContentFilter'} else 'Stop'
                row['backend_finish_seen']=True
                push(recipe.InferenceChunk.finish(getattr(recipe.InferenceFinishReason,reason)))
                row['termination_source']='backend_finish'
            if action=='extra_push':push(recipe.InferenceChunk.text('SHOULD_NOT_APPEAR'))
            elif action=='duplicate_finish':push(recipe.InferenceChunk.finish(recipe.InferenceFinishReason.Stop))
            elif action=='close_then_finish':emit(processor.finish())
            elif action not in {'close'}:
                emit(processor.finish())
                if action=='repeat_flush':row['second_flush_count']=len(processor.finish())
    except Exception as exc:
        err={'type':type(exc).__name__,'message':str(exc)}
        if action in {'no_tokenizer','logprob_mismatch','extra_push','duplicate_finish','close_then_finish'} and row.get('native_error',err)==err:
            row['probe_error']=err
            if action in {'no_tokenizer','logprob_mismatch'}:row['termination_source']='stream_error'
        else:row['unexpected_error']=err
    finally:
        row['native_finished']=processor.finished
        try:
            row['response']=json.loads(response.to_json());row['semantic']=semantic(protocol,row['response'])
        except Exception as exc:row['unexpected_error']={'type':type(exc).__name__,'message':str(exc),'stage':'response observation'}
        processor.close()
    return row


def summarize(plan,rows):
    ids=[x['id'] for x in rows];planned=[x['id'] for x in plan]
    if len(set(ids))!=len(ids) or len(set(planned))!=len(planned) or not set(ids)<=set(planned):
        raise ValueError('duplicate/unexpected result id')
    byid={x['id']:x for x in rows};outcomes=[]
    for job in plan:
        row=byid.get(job['id']);status='unknown';reason='missing or stale contract'
        if row and row.get('contract')==job['contract']:
            checks=row.get('checks',[]);names=[x.get('name') for x in checks]
            if len(names)!=len(set(names)):raise ValueError('duplicate check name')
            found={x.get('name'):x.get('status') for x in checks}
            states=[found.get(n,'unknown') for n in job.get('required_checks',names)]
            status='fail' if 'fail' in states else 'pass' if states and all(x=='pass' for x in states) else 'unknown'
            reason='declared checks'
        outcomes.append({'id':job['id'],'status':status,'reason':reason})
    return {'n':len(plan),'passed':sum(x['status']=='pass' for x in outcomes),'failed':sum(x['status']=='fail' for x in outcomes),
            'unknown':sum(x['status']=='unknown' for x in outcomes),'outcomes':outcomes}
