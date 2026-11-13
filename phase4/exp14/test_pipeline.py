import asyncio
import threading
import queue
import types
import unittest
from unittest.mock import patch

try:
    from pipeline import generate_reply
except ImportError:
    generate_reply = None


class ToyModels:
    """Controlled slow boundary for concurrency tests, never reported as GPU data."""
    def asr(self, pcm): return '测试问题'
    def stream_text(self, text, stop, state):
        try:
            for part in ['第一句。','第二句。']:
                if stop.is_set(): break
                yield part
            state['finish_reason']='cancelled' if stop.is_set() else 'stop'
        finally:
            state['thread_stopped']=True
    def tts(self, text):
        import array
        yield array.array('f',[.1]*480)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_audio_arriving_after_empty_probe_is_still_sent(self):
        import pipeline
        sent=[];chunks=[]
        release_tail=threading.Event();returned=threading.Event()
        class State(dict):
            def __setitem__(self,key,value):
                super().__setitem__(key,value)
                if key=='tts_worker_returned' and value is True:returned.set()
        class RaceQueue(queue.Queue):
            forced=False
            def get_nowait(self):
                try:return super().get_nowait()
                except queue.Empty:
                    if sent and not self.forced:
                        self.forced=True;release_tail.set()
                        if not returned.wait(2):raise AssertionError('TTS did not return')
                    raise
        audio=RaceQueue(100);state=State()
        class M(ToyModels):
            def stream_text(self,text,stop,llm):
                yield '回答。'
                llm.update(finish_reason='stop',thread_stopped=True)
            def tts(self,text):
                yield [.1]*480
                if not release_tail.wait(2):raise AssertionError('empty probe not reached')
                yield [.2]*480
        async def emit(pcm):sent.append(pcm)
        def event(name,**fields):
            if name=='tts_pcm_chunk':chunks.append(fields['samples'])
        boundary=types.SimpleNamespace(Queue=lambda maxsize:audio if maxsize==100 else queue.Queue(maxsize),
                                       Empty=queue.Empty,Full=queue.Full)
        with patch.object(pipeline,'queue',boundary):
            await generate_reply(M(),b'\0\0'*512,'A',emit,event,threading.Event(),state)
        self.assertEqual(sum(chunks),960)
        self.assertEqual(sum(map(len,sent))//2,960)
        self.assertTrue(audio.empty())
        self.assertEqual(state['finish_reason'],'stop')

    async def test_tail_and_terminal_follow_real_workers(self):
        self.assertIsNotNone(generate_reply, 'pipeline not implemented')
        output=[];events=[];state={}
        async def emit(pcm): output.append(pcm)
        await generate_reply(ToyModels(),b'\x00\x00'*16000,'C',emit,
                             lambda name,**fields:events.append((name,fields)),threading.Event(),state)
        self.assertEqual(len(output),2)
        self.assertTrue(state['llm']['thread_stopped'])
        self.assertTrue(state['tts_worker_returned'])
        self.assertEqual(state['text'],'第一句。第二句。')
        self.assertEqual(state['finish_reason'],'stop')
        self.assertTrue(any(name=='first_pcm' for name,_ in events))

    async def test_cancelled_send_waits_compute_cleanup(self):
        self.assertIsNotNone(generate_reply)
        stop=threading.Event();state={}
        async def emit(pcm):
            stop.set()
            raise ConnectionResetError('client gone')
        with self.assertRaises(ConnectionResetError):
            await generate_reply(ToyModels(),b'\x00\x00'*16000,'C',emit,
                                 lambda *a,**kw:None,stop,state)
        self.assertTrue(state['tts_worker_returned'])
        self.assertTrue(state['llm']['thread_stopped'])


if __name__=='__main__':unittest.main()
