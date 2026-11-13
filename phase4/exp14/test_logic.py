import asyncio
import threading
import time
import unittest

try:
    from logic import Endpoint, TextChunks, joined_call, normalized_cer
except ImportError:
    Endpoint = TextChunks = joined_call = normalized_cer = None


class LogicTests(unittest.TestCase):
    def test_endpoint_counts_silence_after_speech_not_initial_silence(self):
        self.assertIsNotNone(Endpoint, 'endpoint logic not implemented')
        e = Endpoint(tail_ms=200, sample_rate=16000)
        self.assertFalse(e.feed(0.0, 8000))
        self.assertFalse(e.feed(0.9, 8512))
        self.assertFalse(e.feed(0.1, 11500))
        self.assertTrue(e.feed(0.1, 11712))
        self.assertEqual(e.last_speech_sample, 8512)
        self.assertFalse(e.feed(0.9, 12224))

    def test_short_pause_does_not_end_500ms_policy(self):
        self.assertIsNotNone(Endpoint)
        e = Endpoint(tail_ms=500, sample_rate=16000)
        self.assertFalse(e.feed(.8, 512))
        self.assertFalse(e.feed(.1, 5312))
        self.assertFalse(e.feed(.8, 5824))
        self.assertTrue(e.feed(.1, 13824))

    def test_sentence_and_character_limit_preserve_tail(self):
        self.assertIsNotNone(TextChunks)
        c = TextChunks(max_chars=8)
        self.assertEqual(c.feed('你好。今天'), ['你好。'])
        self.assertEqual(c.feed('天气很好适合出门'), ['今天天气很好适合'])
        self.assertEqual(c.finish(), ['出门'])
        self.assertEqual(c.finish(), [])

    def test_full_mode_buffers_until_finish(self):
        self.assertIsNotNone(TextChunks)
        c = TextChunks(full=True)
        self.assertEqual(c.feed('一。二。'), [])
        self.assertEqual(c.finish(), ['一。二。'])

    def test_cer_keeps_missing_text_and_ignores_punctuation(self):
        self.assertIsNotNone(normalized_cer)
        self.assertEqual(normalized_cer('你好，世界！', '你好世界'), 0)
        self.assertEqual(normalized_cer('你好世界', '你好'), .5)
        self.assertIsNone(normalized_cer('', '一'))


class ThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancel_waits_actual_worker(self):
        self.assertIsNotNone(joined_call, 'thread join not implemented')
        started = threading.Event()
        stopped = threading.Event()
        def work():
            started.set()
            time.sleep(.12)
            stopped.set()
        task = asyncio.create_task(joined_call(work))
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        self.assertFalse(task.done())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())


if __name__ == '__main__':
    unittest.main()
