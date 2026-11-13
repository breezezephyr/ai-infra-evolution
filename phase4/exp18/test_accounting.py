import unittest
from pathlib import Path
from accounting import union_ns, distribution, assumed_cost, resource_ledger


class AccountingTests(unittest.TestCase):
    def test_overlap_and_duplicate_residency_not_double_counted(self):
        self.assertEqual(union_ns([(0, 10), (5, 20), (0, 10), (30, 40)]), 30)

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            union_ns([(2, 1)])

    def test_unknown_not_zero(self):
        self.assertEqual(distribution([None, 10, 30]),
                         dict(eligible=3, measured=2, unknown=1, p50=20, p95=29, min=10, max=30))
        self.assertIsNone(distribution([None])['p50'])

    def test_no_real_session_denominator_no_real_cost(self):
        self.assertIsNone(assumed_cost(3600, None, 2)['cost_per_session_minute'])
        self.assertAlmostEqual(assumed_cost(3600, 15, 2)['cost_per_session_minute'], 2 / 15)
        with self.assertRaises(ValueError):
            assumed_cost(1, 0, 2)

    def test_resource_gaps_and_clock_mismatch(self):
        with self.assertRaises(ValueError):
            resource_ledger([dict(run_id='x', source={'clock': 'browser'})], {})

    def test_formal_raw_coverage_and_unused_generation_accounting(self):
        from accounting import extract
        result = extract(Path(__file__).resolve().parents[1])
        self.assertEqual(result['formal_n'], 36)
        self.assertEqual(result['policies']['eager']['discarded_tokens'], 1079)
        self.assertEqual(result['policies']['stable2']['speculative_selected'], 0)
        self.assertAlmostEqual(result['input_audio_minutes'], 3.423)
        self.assertAlmostEqual(result['known_inserted_silence_seconds'], 42.57)
        self.assertIsNone(result['actual_session_minutes'])
        self.assertIsNone(result['actual_cost_per_session_minute'])

    def test_duplicate_run_rejected_before_aggregation(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            resource_ledger([{'run_id':'same'},{'run_id':'same'}], {})


if __name__ == '__main__':
    unittest.main()
