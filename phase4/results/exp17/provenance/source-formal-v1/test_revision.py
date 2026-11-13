import unittest
from revision import Gate, LatestInput, canonical


class RevisionTests(unittest.TestCase):
    def test_partial_text_cannot_escape_before_final(self):
        g=Gate('eager');self.assertTrue(g.observe('去上海'))
        g.attach(1);self.assertFalse(g.piece(1,'好的，去上海。'))
        self.assertEqual(g.published,'')
        g.observe('去上海',final=True)
        self.assertEqual(g.published,'好的，去上海。')

    def test_changed_transcript_fences_late_old_draft(self):
        g=Gate('eager');g.observe('去上海');g.attach(1);g.piece(1,'去上海。')
        g.observe('去杭州',final=True)
        self.assertFalse(g.piece(1,'旧稿迟到'))
        g.attach(2);self.assertTrue(g.piece(2,'去杭州。'))
        self.assertEqual(g.published,'去杭州。');self.assertEqual(g.rejected_pieces,1)

    def test_stable2_is_equality_of_observations_not_prefix_agreement(self):
        g=Gate('stable2');self.assertFalse(g.observe('请说缓存'))
        self.assertTrue(g.observe('请说缓存。'))
        g.attach(1);self.assertFalse(g.observe('请说缓存缺点'))
        self.assertIsNone(g.active_draft)
        self.assertTrue(g.observe('请说缓存缺点',final=True))

    def test_endpoint_does_not_start_from_partial(self):
        g=Gate('endpoint');self.assertFalse(g.observe('先去公园'))
        self.assertTrue(g.observe('先去公园',final=True))
        g.attach(1);g.piece(1,'准备好了。');self.assertEqual(g.published,'准备好了。')

    def test_empty_final_is_rejected_and_cannot_reuse_old_text(self):
        g=Gate('eager');g.observe('先去公园');g.attach(1)
        with self.assertRaises(ValueError):g.observe('……',final=True)

    def test_final_reuse_does_not_duplicate_buffered_pieces(self):
        g=Gate('eager');g.observe('比较步行骑车');g.attach(1);g.piece(1,'先看距离。')
        g.observe('比较步行骑车。',final=True);g.piece(1,'再看天气。')
        self.assertEqual(g.published,'先看距离。再看天气。')
        self.assertEqual(g.committed_draft,1)

    def test_latest_pending_input_preserves_running_and_final(self):
        q=LatestInput();q.offer(100);self.assertEqual(q.take(),(100,False))
        q.offer(200);q.offer(300);self.assertEqual(q.replaced,1)
        q.offer(400,final=True);self.assertEqual(q.take(),(400,True))
        with self.assertRaises(ValueError):q.offer(500)


if __name__=='__main__':unittest.main()
