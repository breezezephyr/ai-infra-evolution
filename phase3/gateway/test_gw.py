"""准入逻辑单测：python3 -m unittest phase3/gateway/test_gw.py"""
import asyncio, unittest, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from gw import Router, Admission, estimate_from_body

def run(c): return asyncio.run(c)

class TestAdmission(unittest.TestCase):
    def test_pass_never_blocks(self):
        a = Admission("pass", 10, False)
        self.assertEqual(run(a.acquire(100, 100, 1)), "admit")
        self.assertEqual(a.inflight_tokens, 100)

    def test_reject_when_full(self):
        a = Admission("reject", 1000, False)
        self.assertEqual(run(a.acquire(600, 100, 1)), "admit")
        self.assertEqual(run(a.acquire(600, 100, 1)), "reject")
        a.release(600)
        self.assertEqual(run(a.acquire(600, 100, 1)), "admit")
        self.assertEqual(a.counters["rejected"], 1)

    def test_queue_admits_after_release(self):
        async def go():
            a = Admission("queue", 1000, False)
            await a.acquire(800, 100, 1)
            t = asyncio.create_task(a.acquire(500, 100, 2))
            await asyncio.sleep(0.05)
            self.assertEqual(len(a.queue), 1)
            a.release(800)
            self.assertEqual(await t, "admit")
            self.assertEqual(a.inflight_tokens, 500)
        run(go())

    def test_queue_timeout(self):
        async def go():
            a = Admission("queue", 1000, False)
            await a.acquire(800, 100, 1)
            self.assertEqual(await a.acquire(500, 100, 0.05), "queue_timeout")
            self.assertEqual(len(a.queue), 0)
            self.assertEqual(a.counters["queue_timeout"], 1)
        run(go())

    def test_fcfs_does_not_skip_head(self):
        """队首大件放不下时，后面的小件也不能插队（保 FCFS）。"""
        async def go():
            a = Admission("queue", 1000, False)
            await a.acquire(700, 100, 1)
            big = asyncio.create_task(a.acquire(600, 100, 2))
            await asyncio.sleep(0.01)
            small = asyncio.create_task(a.acquire(100, 100, 2))
            await asyncio.sleep(0.01)
            self.assertFalse(small.done())
            a.release(700)
            await asyncio.sleep(0.01)
            self.assertTrue(big.done()); self.assertTrue(small.done())
            self.assertEqual(a.inflight_tokens, 700)
        run(go())

    def test_priority_order(self):
        async def go():
            a = Admission("queue", 1000, True)
            await a.acquire(1000, 100, 1)
            order = []
            async def w(tok, prio, name):
                await a.acquire(tok, prio, 2); order.append(name)
            ts = [asyncio.create_task(w(300, 100, "batch1")), asyncio.create_task(w(300, 100, "batch2")), asyncio.create_task(w(300, 1, "interactive"))]
            await asyncio.sleep(0.01)
            a.release(1000)
            await asyncio.gather(*ts)
            self.assertEqual(order[0], "interactive")
        run(go())

    def test_priority_jumps_in_when_it_fits(self):
        # 队里有放不下的大件，高优小件放得下 -> 立即上车，不等 release
        async def go():
            a = Admission("queue", 1000, True)
            await a.acquire(800, 100, 1)
            big = asyncio.create_task(a.acquire(500, 100, 2))
            await asyncio.sleep(0.01)
            r = await asyncio.wait_for(a.acquire(150, 1, 2), 0.1)
            self.assertEqual(r, "admit"); self.assertFalse(big.done())
            a.release(800); a.release(150); await big
        run(go())

    def test_fcfs_small_still_waits_behind_head(self):
        async def go():
            a = Admission("queue", 1000, False)
            await a.acquire(800, 100, 1)
            big = asyncio.create_task(a.acquire(500, 100, 2))
            await asyncio.sleep(0.01)
            small = asyncio.create_task(a.acquire(150, 1, 2))
            await asyncio.sleep(0.05)
            self.assertFalse(small.done())
            a.release(800); await big; await small
        run(go())

    def test_reserve_keeps_seat_for_high_prio(self):
        async def go():
            a = Admission("reject", 1000, True, reserve=300)
            self.assertEqual(await a.acquire(700, 100, 1), "admit")
            self.assertEqual(await a.acquire(100, 100, 1), "reject")   # 低优只能用 700
            self.assertEqual(await a.acquire(300, 1, 1), "admit")      # 高优吃预留
        run(go())

class TestRouter(unittest.TestCase):
    def test_rr_alternates(self):
        r = Router([1, 2], "rr")
        self.assertEqual([r.pick("x")[0] for _ in range(4)], [1, 2, 1, 2])

    def test_hash_sticky_by_prefix(self):
        r = Router([1, 2], "hash", hash_chars=8)
        a = r.pick("PREFIX_A" + "q1")[0]
        self.assertTrue(all(r.pick("PREFIX_A" + s)[0] == a for s in ("q2", "zz", "")))
        homes = {r.pick(f"P{i:07d}")[0] for i in range(20)}
        self.assertEqual(homes, {1, 2})

    def test_bounded_spills_when_hot(self):
        r = Router([1, 2], "bounded", hash_chars=8, bound=1.25)
        home, spilled = r.pick("PREFIX_A"); other = 3 - home
        self.assertFalse(spilled)  # 空载不改道
        r.inflight[home] = 4; r.inflight[other] = 1  # 上限 ⌈1.25×6/2⌉=4，再来一条就 5
        self.assertEqual(r.pick("PREFIX_A"), (other, True))
        r.inflight[home] = 1
        self.assertEqual(r.pick("PREFIX_A"), (home, False))

class TestGatewayInit(unittest.TestCase):
    def test_log_ready_before_any_drain(self):
        # 回归：_drain_cut 曾把 __init__ 尾部吞进自己的函数体，重启后到第一次排空前一行日志都不记
        import tempfile, gw
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as f:
            gw.LOG = f.name
            g = gw.Gateway(); g.record(outcome="probe")
            self.assertIn("probe", open(f.name).read())

class TestEstimate(unittest.TestCase):
    def test_completions(self):
        self.assertEqual(estimate_from_body(b'{"prompt":"hi","max_tokens":64}'), ("hi", 64))
    def test_chat(self):
        p, m = estimate_from_body(b'{"messages":[{"role":"user","content":"a"},{"role":"assistant","content":"b"}]}')
        self.assertEqual((p, m), ("a\nb", 16))

if __name__ == "__main__":
    unittest.main()
