import asyncio
import threading
import time
import unittest
from run_gpu import run_case


class TinyModels:
    """Only model boundary is a controlled fixture; scheduler, threads and gate are real."""
    def asr(self, pcm):
        return '先去上海公园' if len(pcm)<6400 else '改去杭州公园'

    def stream_text(self,text,stop,state):
        try:
            yield text+'，'
            time.sleep(.004)
            if not stop.is_set():yield '记得带水。'
            state.update(generated_tokens=8,finish_reason='cancelled' if stop.is_set() else 'stop')
        finally:state['thread_stopped']=True


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_final_prompt_never_publishes_the_old_draft(self):
        result=await run_case(TinyModels(),{'id':'tiny','reference_text':'改去杭州公园'},b'\0\0'*3200,'eager','toy-race',40)
        self.assertIsNone(result['error'])
        self.assertEqual(result['validated_text'],'改去杭州公园，记得带水。')
        self.assertGreaterEqual(result['wasted_generated_tokens'],8)
        self.assertTrue(all(d['thread_stopped'] for d in result['drafts']))
        complete=next(e['monotonic_ns'] for e in result['events'] if e['event']=='input_complete')
        self.assertTrue(all(e['monotonic_ns']>=complete for e in result['events'] if e['event']=='validated_text_published'))

    async def test_identical_final_reuses_computed_text_without_new_generation(self):
        class M(TinyModels):
            def asr(self,pcm):return '先去上海公园'
        result=await run_case(M(),{'id':'tiny','reference_text':'先去上海公园'},b'\0\0'*3200,'eager','toy-reuse',40)
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['drafts']),1)
        self.assertTrue(result['committed_draft_started_before_input_end'])
        self.assertEqual(result['validated_text'],'先去上海公园，记得带水。')

    async def test_recognizer_failure_cannot_leave_generation_worker_running(self):
        class M(TinyModels):
            def asr(self,pcm):
                if len(pcm)>=6400:raise RuntimeError('controlled ASR error')
                return '先去上海公园'
        result=await run_case(M(),{'id':'tiny','reference_text':'先去上海公园'},b'\0\0'*3200,'eager','toy-error',40)
        self.assertIn('controlled ASR error',result['error'])
        self.assertTrue(all(d['thread_stopped'] for d in result['drafts']))
        self.assertFalse(any(t.name.startswith('exp17-draft-') for t in threading.enumerate()))


if __name__=='__main__':unittest.main()
