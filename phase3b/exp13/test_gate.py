import asyncio
import unittest
from gate import moderate

async def stream(parts, interval=.002, closed=None):
    try:
        for text in parts:
            await asyncio.sleep(interval)
            yield text
    finally:
        if closed is not None: closed.append(True)

class GateTests(unittest.IsolatedAsyncioTestCase):
    async def run_gate(self, parts, reviewer, **kwargs):
        seen=[]
        async def emit(text): seen.append(text)
        result=await moderate(stream(parts),reviewer,emit,**kwargs)
        return ''.join(seen),result

    async def test_sync_withholds_rejected_sentence_across_delta_boundaries(self):
        async def review(text): return 'BAD' in text
        text,result=await self.run_gate(['前文。BA','D','。后文。'],review)
        self.assertEqual(text,'前文。')
        self.assertEqual(result['finish_reason'],'content_filter')

    async def test_final_unpunctuated_tail_is_reviewed(self):
        async def review(text): return 'BAD' in text
        text,result=await self.run_gate(['前文。','BAD'],review)
        self.assertEqual(text,'前文。')
        self.assertEqual(result['finish_reason'],'content_filter')

    async def test_no_punctuation_forces_a_bounded_review_window(self):
        calls=[]
        async def review(text):calls.append(text);return False
        text,result=await self.run_gate(['甲'*19],review,max_chars=8)
        self.assertEqual(text,'甲'*19)
        self.assertEqual(list(map(len,calls)),[8,8,3])
        self.assertEqual(result['finish_reason'],'stop')

    async def test_review_timeout_fails_closed_and_is_not_reported_as_allow(self):
        async def review(text):await asyncio.sleep(1);return False
        text,result=await self.run_gate(['正文。'],review,review_timeout=.01)
        self.assertEqual(text,'')
        self.assertEqual(result['finish_reason'],'review_timeout')

    async def test_async_can_leak_but_still_waits_for_final_reviews(self):
        async def review(text):await asyncio.sleep(.02);return 'BAD' in text
        text,result=await self.run_gate(['BAD。','后文。'],review,mode='async')
        self.assertTrue(text.startswith('BAD。'))
        self.assertEqual(result['finish_reason'],'content_filter')
        self.assertEqual(result['blocked_start'],0)

    async def test_async_early_block_cancels_slow_later_reviews(self):
        cancelled=[]
        async def review(text):
            try:
                await asyncio.sleep(.01 if text=='BAD。' else 1)
                return text=='BAD。'
            except asyncio.CancelledError:cancelled.append(text);raise
        text,result=await self.run_gate(['BAD。','后文。'],review,mode='async')
        self.assertEqual(result['finish_reason'],'content_filter')
        self.assertIn('后文。',cancelled)

    async def test_consumer_disconnect_closes_source(self):
        closed=[]
        async def review(text):return False
        async def emit(text):raise ConnectionResetError('client left')
        with self.assertRaises(ConnectionResetError):
            await moderate(stream(['正文。','后文。'],closed=closed),review,emit,mode='async')
        self.assertEqual(closed,[True])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_and_sse_frames_can_cross_every_network_boundary(self):
        from transport import text_deltas,sse
        class Content:
            async def iter_any(self):
                raw=sse({'choices':[{'delta':{'content':'中文。'}}]})+b'data: [DONE]\n\n'
                for b in raw:yield bytes([b])
        class Response:content=Content()
        got=[x async for x in text_deltas(Response())]
        self.assertEqual(got,['中文。'])

    async def test_network_eof_is_not_successful_completion(self):
        from transport import text_deltas,sse
        class Content:
            async def iter_any(self):
                yield sse({'choices':[{'delta':{'content':'尾句'}}]})
        class Response:content=Content()
        with self.assertRaises(EOFError):
            _=[x async for x in text_deltas(Response())]

class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_review_is_not_an_allow(self):
        async def review(text):return 'ALLOW'
        async def emit(text):raise AssertionError('invalid review leaked')
        r=await moderate(stream(['正文。']),review,emit)
        self.assertEqual(r['finish_reason'],'review_error')

    async def test_review_backlog_has_a_finite_cutoff(self):
        async def review(text):await asyncio.sleep(1);return False
        seen=[]
        async def emit(text):seen.append(text)
        r=await moderate(stream(['甲。乙。丙。']),review,emit,mode='async',max_pending=1)
        self.assertEqual(r['finish_reason'],'review_backlog')
        self.assertLessEqual(len(r['checks']),1)

class RegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_immediate_reviews_do_not_false_backlog_on_one_large_delta(self):
        async def review(text):return False
        seen=[]
        async def emit(text):seen.append(text)
        r=await moderate(stream(['好。'*9]),review,emit,mode='async',max_pending=8)
        self.assertEqual(r['finish_reason'],'stop')
        self.assertEqual(len(r['checks']),9)
        self.assertEqual(''.join(seen),'好。'*9)

    async def test_upstream_self_cancel_does_not_leave_consumer_waiting(self):
        async def source():
            yield '好。'
            raise asyncio.CancelledError()
        async def review(text):return False
        async def emit(text):pass
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(moderate(source(),review,emit),1.0)

    async def test_source_close_failure_is_propagated_without_waiting_forever(self):
        class Source:
            def __aiter__(self):return self
            async def __anext__(self):raise StopAsyncIteration
            async def aclose(self):raise ValueError('close failed')
        async def review(text):return False
        async def emit(text):pass
        with self.assertRaisesRegex(ValueError,'close failed'):
            await asyncio.wait_for(moderate(Source(),review,emit),1.0)


class GPUAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_review_waits_for_actual_worker_completion(self):
        import threading
        from async_threads import joined_thread_call
        began=threading.Event();release=threading.Event();finished=threading.Event()
        def worker():
            began.set();release.wait(1);finished.set();return True
        task=asyncio.create_task(joined_thread_call(worker))
        await asyncio.to_thread(began.wait,1)
        task.cancel();await asyncio.sleep(.01)
        try:
            self.assertFalse(task.done())
        finally:
            release.set()
            try:await task
            except asyncio.CancelledError:pass
        self.assertTrue(finished.is_set())

    async def test_sse_adapter_preserves_upstream_length_reason(self):
        from transport import text_deltas,sse
        class Content:
            async def iter_any(self):
                yield sse({'choices':[{'delta':{'content':'正文'},'finish_reason':None}]})
                yield sse({'choices':[{'delta':{},'finish_reason':'length'}]})
                yield b'data: [DONE]\n\n'
        class Response:content=Content()
        reasons=[]
        got=[x async for x in text_deltas(Response(),on_finish=reasons.append)]
        self.assertEqual(got,['正文'])
        self.assertEqual(reasons,['length'])

class RepeatedCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_cannot_detach_the_worker(self):
        import threading
        from async_threads import joined_thread_call
        began=threading.Event();release=threading.Event();finished=threading.Event()
        def worker():began.set();release.wait(1);finished.set()
        task=asyncio.create_task(joined_thread_call(worker))
        await asyncio.to_thread(began.wait,1)
        try:
            task.cancel();await asyncio.sleep(.01)
            task.cancel();await asyncio.sleep(.01)
            self.assertFalse(task.done())
        finally:
            release.set()
            try:await task
            except asyncio.CancelledError:pass
        self.assertTrue(finished.is_set())

if __name__=='__main__':unittest.main()
