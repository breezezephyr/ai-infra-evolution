import threading
import time
import unittest

from engine import Generation, retained_history


class ToyModels:
    """Deterministic race fixtures, never GPU measurements."""
    def stream_text(self, prompt, stop, state, history=None):
        try:
            yield '第一句。第二句。'
            state['finish_reason'] = 'stop'
        finally:
            state['thread_stopped'] = True

    def tts(self, text):
        return iter([[.1] * 960])


class EngineTests(unittest.TestCase):
    def test_normal_tail_is_not_lost(self):
        g = Generation(ToyModels(), 1, '测试', [])
        g.start()
        messages = []
        while not g.finished() or not g.output.empty():
            item = g.pop(.1)
            if item: messages.append(item)
        g.join()
        self.assertEqual(sum(len(m['pcm']) // 2 for m in messages if m['type'] == 'audio'), 1920)
        self.assertEqual(g.state['computed_samples'], 1920)
        self.assertTrue(g.state['llm_thread_stopped'])
        self.assertTrue(g.state['tts_thread_stopped'])

    def test_cancel_waits_native_call_then_discards_result(self):
        entered, release = threading.Event(), threading.Event()
        class M(ToyModels):
            def tts(self, text):
                entered.set()
                if not release.wait(2): raise RuntimeError('fixture timed out')
                yield [.1] * 960
        g = Generation(M(), 1, '测试', [])
        g.start()
        self.assertTrue(entered.wait(2))
        g.cancel()
        self.assertFalse(g.finished())
        release.set(); g.join()
        self.assertEqual(g.state['computed_samples'], 960)
        self.assertEqual(g.state['discarded_after_stop_samples'], 960)
        self.assertIsNone(g.pop(.01))
        self.assertTrue(g.state['tts_thread_stopped'])

    def test_cancel_unblocks_bounded_output_and_joins(self):
        g = Generation(ToyModels(), 1, '测试', [], queue_limit=1)
        g.start(); time.sleep(.02); g.cancel(); g.join()
        self.assertTrue(g.finished())
        self.assertIsNone(g.pop(.01))
        self.assertTrue(g.output.empty())
        self.assertTrue(g.texts.empty())

    def test_history_keeps_only_fully_rendered_complete_segments(self):
        parts = [{'text':'第一句。','start':0,'end':960},
                 {'text':'第二句。','start':960,'end':1920}]
        self.assertEqual(retained_history(parts, 0), '')
        self.assertEqual(retained_history(parts, 959), '')
        self.assertEqual(retained_history(parts, 960), '第一句。')
        self.assertEqual(retained_history(parts, 1500), '第一句。')
        self.assertEqual(retained_history(parts, 1920), '第一句。第二句。')
        with self.assertRaises(ValueError): retained_history(parts, -1)


if __name__ == '__main__': unittest.main()
