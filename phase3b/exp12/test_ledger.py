"""防止缓存重复收费、同卡时间重复分摊、排队超时冒充真实等待。"""
import unittest
from ledger import token_charge, split_card_time, reconstruct_queue


class LedgerTests(unittest.TestCase):
    def test_cached_input_is_subset_not_extra_input(self):
        # 1000 输入中 800 命中，输出 100；费率 1 / .2 / 3 每千 token。
        self.assertAlmostEqual(token_charge(1000, 800, 100), .66)

    def test_missing_cache_cannot_be_billed_as_zero_hits(self):
        self.assertIsNone(token_charge(1000, None, 100))

    def test_impossible_token_count_fails(self):
        for p, c, o in [(10, 11, 1), (10, -1, 1), (10, 1, -1)]:
            with self.assertRaises(ValueError):
                token_charge(p, c, o)

    def test_shared_card_seconds_conserve_even_for_two_replicas(self):
        # A:0..4 B:2..6，共享区间各分一半；6..8 不分配。
        got = split_card_time([{'id': 'A', 'start': 0, 'end': 4},
                               {'id': 'B', 'start': 2, 'end': 6}], 0, 8)
        self.assertEqual(got['shares'], {'A': 3, 'B': 3})
        self.assertEqual(got['unassigned_s'], 2)
        self.assertEqual(got['window_s'], 8)

    def test_queue_timeouts_remain_censored(self):
        got = reconstruct_queue([
            {'outcome': 'ok', 'ts': 15, 'total_ms': 3000, 'queue_ms': 2000, 'est_ms': 5},
            {'outcome': 'queue_timeout', 'ts': 21, 'queue_ms': 10000, 'est_ms': 5},
        ])
        self.assertEqual(got[0]['entry'], 10)
        self.assertEqual(got[0]['exit'], 12)
        self.assertEqual(got[0]['wait_s'], 2)
        self.assertIsNone(got[1]['wait_s'])
        self.assertEqual(got[1]['lower_bound_s'], 10)


if __name__ == '__main__':
    unittest.main()
