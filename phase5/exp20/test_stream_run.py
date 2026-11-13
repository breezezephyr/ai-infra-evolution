"""Catch lost terminal provenance, fabricated success and omitted records."""
import unittest
import json
from unittest.mock import patch
import stream_run
from stream_run import run_case, summarize


class BoundaryTests(unittest.TestCase):
    def case(self, **kw):
        return {'id':'check','raw':'说到一半','thinking':False,'action':'Stop','stop':[],**kw}

    def test_eof_flush_does_not_prove_backend_completion(self):
        row=run_case(self.case(action='eof'))
        self.assertEqual(row.get('termination_source'),'unconfirmed_eof')
        self.assertTrue(row.get('native_finished'))
        self.assertEqual(row.get('semantic',{}).get('finish'),'stop')
        self.assertFalse(row.get('backend_finish_seen'))

    def test_close_preserves_partial_text_without_success(self):
        row=run_case(self.case(action='close'))
        self.assertEqual(row.get('termination_source'),'client_abort')
        self.assertEqual(row.get('semantic',{}).get('text'),'说到一半')
        self.assertIsNone(row.get('semantic',{}).get('finish'))
        self.assertFalse(row.get('native_finished'))

    def test_parser_stop_does_not_push_remaining_chunks(self):
        row=run_case(self.case(raw='车已到站END20不应显示',stop=['END20']),pattern='unit')
        self.assertEqual(row.get('semantic',{}).get('text'),'车已到站')
        self.assertEqual(row.get('termination_source'),'parser_stop')
        self.assertGreater(row.get('unsubmitted_units',0),0)
        self.assertIsNone(row.get('unexpected_error'))

    def test_post_finish_error_keeps_known_terminal_and_events(self):
        row=run_case(self.case(action='extra_push'))
        self.assertEqual(row.get('termination_source'),'backend_finish')
        self.assertEqual(row.get('probe_error',{}).get('type'),'RuntimeError')
        self.assertEqual(row.get('semantic',{}).get('text'),'说到一半')
        self.assertTrue(row.get('events'))

    def test_tokens_without_tokenizer_is_recorded_as_stream_error(self):
        row=run_case(self.case(action='no_tokenizer'))
        self.assertEqual(row.get('termination_source'),'stream_error')
        self.assertEqual(row.get('probe_error',{}).get('type'),'RuntimeError')
        self.assertFalse(row.get('native_finished'))

    def test_missing_result_remains_in_denominator(self):
        result=summarize([{'id':'a','contract':'x'},{'id':'b','contract':'y'}],[])
        self.assertEqual(result.get('n'),2)
        self.assertEqual(result.get('unknown'),2)
        self.assertEqual(result.get('passed'),0)

    def test_old_contract_cannot_pass_new_expectation(self):
        result=summarize([{'id':'a','contract':'new'}],[{'id':'a','contract':'old','checks':[{'status':'pass'}]}])
        self.assertEqual(result.get('unknown'),1)
        self.assertEqual(result.get('passed'),0)

    def test_duplicate_records_cannot_inflate_success(self):
        with self.assertRaises(ValueError):
            summarize([{'id':'a','contract':'x'}],[{'id':'a'},{'id':'a'}])

    def response_fault(self, *, terminal_only=False, serialization=False):
        """Keep real response behavior, injecting only an observation failure."""
        real=stream_run.RESPONSE['chat']
        def fails(out):
            return not terminal_only or any(c.get('finish_reason') is not None
                for c in json.loads(out.to_json()).get('choices',[]))
        class ObservedResponse:
            def __init__(self,*args):self.inner=real(*args)
            @staticmethod
            def sse_event_name(out):
                if serialization and fails(out):raise RuntimeError('event observer failed')
                return real.sse_event_name(out)
            def accumulate(self,out):
                if not serialization and fails(out):raise RuntimeError('event observer failed')
                self.inner.accumulate(out)
            def to_json(self):return self.inner.to_json()
        return patch.dict(stream_run.RESPONSE,{'chat':ObservedResponse})

    def processor_fault(self, *, push_error=False, finish_error=False,
                        second_finish_error=False, close_error=False):
        """Delegate to the real processor except at the fault under test."""
        real=stream_run.recipe.StreamProcessor
        class ObservedProcessor:
            def __init__(self,*args):self.inner=real(*args);self.flushes=0
            @property
            def finished(self):return self.inner.finished
            def push(self,chunk):
                if push_error:raise RuntimeError('native push sentinel')
                return self.inner.push(chunk)
            def finish(self):
                self.flushes+=1
                if finish_error or (second_finish_error and self.flushes>1):
                    raise RuntimeError('native finish sentinel')
                return self.inner.finish()
            def close(self):
                self.inner.close()
                if close_error:raise RuntimeError('native close sentinel')
        return patch.object(stream_run.recipe,'StreamProcessor',ObservedProcessor)

    def test_observation_errors_cannot_satisfy_any_expected_native_probe(self):
        for action in ('no_tokenizer','logprob_mismatch','extra_push','duplicate_finish','close_then_finish'):
            for serialization in (False,True):
                with self.subTest(action=action,serialization=serialization), self.response_fault(serialization=serialization):
                    row=run_case(self.case(action=action))
                    self.assertIsNotNone(row.get('unexpected_error'))
                    self.assertNotIn('probe_error',row)
                    self.assertNotIn('native_error',row)

    def test_native_failure_before_target_probe_is_unexpected(self):
        with self.processor_fault(push_error=True):
            row=run_case(self.case(action='extra_push'))
        self.assertIsNotNone(row.get('unexpected_error'))
        self.assertNotIn('probe_error',row)
        self.assertEqual(row.get('native_error',{}).get('message'),'native push sentinel')
        self.assertFalse(row['backend_finish_seen'])

    def test_close_then_finish_records_actual_native_finish_error(self):
        row=run_case(self.case(action='close_then_finish'))
        self.assertEqual(row.get('termination_source'),'client_abort')
        self.assertEqual(row.get('probe_error',{}).get('type'),'RuntimeError')
        self.assertEqual(row.get('native_error'),row.get('probe_error'))
        self.assertIsNone(row.get('unexpected_error'))
        self.assertFalse(row['backend_finish_seen'])

    def test_eof_native_finish_failure_preserves_eof_origin(self):
        with self.processor_fault(finish_error=True):
            row=run_case(self.case(action='eof'))
        self.assertEqual(row.get('termination_source'),'unconfirmed_eof')
        self.assertEqual(row.get('native_error',{}).get('message'),'native finish sentinel')
        self.assertIsNotNone(row.get('unexpected_error'))
        self.assertNotIn('probe_error',row)
        self.assertFalse(row['backend_finish_seen'])

    def test_eof_does_not_invent_a_second_finish_method_call(self):
        with self.processor_fault(second_finish_error=True):
            row=run_case(self.case(action='eof'))
        self.assertIsNone(row.get('unexpected_error'))
        self.assertEqual(row['termination_source'],'unconfirmed_eof')
        self.assertEqual(row['semantic']['text'],'说到一半')

    def test_terminal_observation_failure_keeps_backend_and_eof_origins(self):
        for action,source,backend in (('Stop','backend_finish',True),('eof','unconfirmed_eof',False)):
            with self.subTest(action=action), self.response_fault(terminal_only=True):
                row=run_case(self.case(action=action))
                self.assertEqual(row.get('termination_source'),source)
                self.assertEqual(row['backend_finish_seen'],backend)
                self.assertTrue(row['native_finished'])
                self.assertIsNotNone(row.get('unexpected_error'))
                self.assertNotIn('native_error',row)

    def test_parser_stop_observation_failure_preserves_origin_and_remainder(self):
        with self.response_fault(terminal_only=True):
            row=run_case(self.case(raw='车已到站END20不应显示',stop=['END20']),pattern='unit')
        self.assertEqual(row.get('termination_source'),'parser_stop')
        self.assertGreater(row.get('unsubmitted_units',0),0)
        self.assertTrue(row.get('native_finished_after_data'))
        self.assertFalse(row['backend_finish_seen'])
        self.assertIsNotNone(row.get('unexpected_error'))

    def test_close_failure_is_recorded_without_escaping_or_losing_abort_origin(self):
        with self.processor_fault(close_error=True):
            row=run_case(self.case(action='close'))
        self.assertEqual(row.get('termination_source'),'client_abort')
        self.assertIsNotNone(row.get('unexpected_error'))
        self.assertFalse(row['backend_finish_seen'])
        self.assertEqual(row.get('semantic',{}).get('text'),'说到一半')

    def test_cleanup_failure_does_not_hide_a_native_probe_error(self):
        with self.processor_fault(close_error=True):
            row=run_case(self.case(action='extra_push'))
        self.assertEqual(row['termination_source'],'backend_finish')
        self.assertEqual(row.get('probe_error',{}).get('type'),'RuntimeError')
        self.assertIsNotNone(row.get('unexpected_error'))
        self.assertEqual(row.get('semantic',{}).get('text'),'说到一半')

    def test_later_response_observation_error_does_not_replace_the_first_error(self):
        with self.response_fault(), patch('stream_run.semantic',side_effect=ValueError('final observer failed')):
            row=run_case(self.case())
        self.assertEqual(row.get('unexpected_error',{}).get('message'),'event observer failed')
        self.assertTrue(any(e.get('message')=='final observer failed' for e in row.get('unexpected_errors',[])))

    def test_request_setup_failure_is_a_recorded_unexpected_error(self):
        with patch.dict(stream_run.REQUEST,{'chat':lambda _: (_ for _ in ()).throw(ValueError('request sentinel'))}):
            row=run_case(self.case(action='extra_push'))
        self.assertEqual(row.get('unexpected_error',{}).get('message'),'request sentinel')
        self.assertNotIn('probe_error',row)
        self.assertNotIn('native_error',row)
        self.assertEqual(row['termination_source'],'unknown')


class SummaryContractTests(unittest.TestCase):
    def test_result_supplied_checks_cannot_define_the_plan(self):
        result=summarize([{'id':'a','contract':'current'}],
                         [{'id':'a','contract':'current','checks':[{'name':'arbitrary','status':'pass'}]}])
        self.assertEqual((result['n'],result['passed'],result['unknown']),(1,0,1))

    def test_missing_or_empty_contracts_cannot_verify_each_other(self):
        for contract in (None,''):
            with self.subTest(contract=contract):
                result=summarize([{'id':'a','contract':contract,'required_checks':['content']}],
                    [{'id':'a','contract':contract,'checks':[{'name':'content','status':'pass'}]}])
                self.assertEqual((result['passed'],result['unknown']),(0,1))
        result=summarize([{'id':'a','required_checks':['content']}],
            [{'id':'a','checks':[{'name':'content','status':'pass'}]}])
        self.assertEqual((result['passed'],result['unknown']),(0,1))

    def test_duplicate_required_checks_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize([{'id':'a','contract':'current','required_checks':['content','content']}],
                [{'id':'a','contract':'current','checks':[{'name':'content','status':'pass'}]}])

    def test_unexpected_error_cannot_pass_even_when_declared_checks_pass(self):
        result=summarize([{'id':'a','contract':'current','required_checks':['content']}],
            [{'id':'a','contract':'current','unexpected_error':{'type':'RuntimeError'},
              'checks':[{'name':'content','status':'pass'}]}])
        self.assertEqual((result['passed'],result['failed'],result['unknown']),(0,1,0))

    def test_missing_stale_unknown_failed_and_passed_rows_share_one_denominator(self):
        plan=[{'id':name,'contract':'current','required_checks':['content','terminal']}
              for name in ('missing','stale','unsigned','unknown','failed','passed')]
        checks=[{'name':'content','status':'pass'},{'name':'terminal','status':'pass'}]
        rows=[{'id':'stale','contract':'old','checks':[{'name':'content','status':'fail'}]},
              {'id':'unsigned','checks':checks},
              {'id':'unknown','contract':'current','checks':[{'name':'content','status':'pass'}]},
              {'id':'failed','contract':'current','checks':[{'name':'content','status':'fail'}]},
              {'id':'passed','contract':'current','checks':checks}]
        result=summarize(plan,rows)
        self.assertEqual((result['n'],result['passed'],result['failed'],result['unknown']),(6,1,1,4))

    def test_duplicate_current_checks_and_unknown_result_ids_are_rejected(self):
        plan=[{'id':'a','contract':'current','required_checks':['content']}]
        for rows in ([{'id':'a','contract':'current','checks':[
                         {'name':'content','status':'pass'},{'name':'content','status':'fail'}]}],
                     [{'id':'outside','contract':'current','checks':[]}]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):summarize(plan,rows)


if __name__=='__main__':unittest.main()
