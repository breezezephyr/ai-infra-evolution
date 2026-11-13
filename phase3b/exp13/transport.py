"""OpenAI风格正文 SSE 适配，按事件拆包，不按网络读块算token。"""
import json
import re


async def text_deltas(response,on_finish=None):
    buffer=b''
    done=False
    async for chunk in response.content.iter_any():
        buffer+=chunk
        if len(buffer)>1_048_576:raise ValueError('SSE frame too large')
        while True:
            match=re.search(rb'\r?\n\r?\n',buffer)
            if not match:break
            frame,buffer=buffer[:match.start()],buffer[match.end():]
            lines=frame.decode('utf-8').replace('\r\n','\n').split('\n')
            values=[line[5:].lstrip(' ') for line in lines if line.startswith('data:')]
            if not values:continue
            payload='\n'.join(values)
            if payload=='[DONE]':done=True;return
            item=json.loads(payload)
            if 'error' in item:raise ValueError('upstream error event')
            for choice in item.get('choices',[]):
                if choice.get('finish_reason') and on_finish is not None:on_finish(choice['finish_reason'])
                text=choice.get('delta',{}).get('content') or choice.get('text')
                if text:yield text
    if not done:raise EOFError('upstream stream ended without DONE')


def sse(data):
    return ('data: '+json.dumps(data,ensure_ascii=False)+'\n\n').encode('utf-8')
