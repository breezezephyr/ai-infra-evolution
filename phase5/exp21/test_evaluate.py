import unittest
from jsonschema.exceptions import SchemaError
from evaluate import evaluate,summarize

SCHEMA={'type':'object','properties':{'n':{'type':'integer'}},'required':['n'],'additionalProperties':False}

class EvaluationTests(unittest.TestCase):
    def test_json_is_not_schema_success(self):
        r=evaluate('{"n":"3"}',SCHEMA,{'n':3})
        self.assertTrue(r.get('json_valid'));self.assertIs(r.get('schema_valid'),False);self.assertIs(r.get('business_correct'),False)
    def test_schema_is_not_answer_correctness(self):
        r=evaluate('{"n":2}',SCHEMA,{'n':3})
        self.assertTrue(r.get('schema_valid'));self.assertIs(r.get('business_correct'),False)
    def test_fenced_json_is_not_silently_extracted(self):
        self.assertIs(evaluate('```json\n{"n":3}\n```',SCHEMA,{'n':3}).get('json_valid'),False)
    def test_duplicate_keys_are_rejected(self):
        self.assertIs(evaluate('{"n":2,"n":3}',SCHEMA,{'n':3}).get('json_valid'),False)
    def test_nan_is_not_json(self):
        self.assertIs(evaluate('{"n":NaN}',SCHEMA,{'n':3}).get('json_valid'),False)
    def test_boolean_does_not_match_integer_answer(self):
        r=evaluate('{"n":true}',SCHEMA,{'n':1})
        self.assertIs(r.get('schema_valid'),False);self.assertIs(r.get('business_correct'),False)
    def test_valid_json_with_length_finish_is_not_deliverable_success(self):
        r=evaluate('{"n":3}',SCHEMA,{'n':3},'length')
        self.assertTrue(r.get('business_correct'));self.assertIs(r.get('complete'),False);self.assertIs(r.get('deliverable'),False)
    def test_extra_field_fails_schema(self):
        self.assertIs(evaluate('{"n":3,"extra":0}',SCHEMA,{'n':3}).get('schema_valid'),False)
    def test_invalid_schema_is_an_experiment_error(self):
        with self.assertRaises(SchemaError):evaluate('{}',{'type':'invented'},{})
    def test_missing_record_stays_in_denominator(self):
        s=summarize([{'id':'a','contract':'x'},{'id':'b','contract':'y'}],[])
        self.assertEqual(s.get('n'),2);self.assertEqual(s.get('missing_or_stale'),2)
    def test_stale_contract_cannot_count_as_success(self):
        s=summarize([{'id':'a','contract':'new'}],[{'id':'a','contract':'old','accepted':True,'evaluation':{'deliverable':True}}])
        self.assertEqual(s.get('accepted'),0);self.assertEqual(s.get('missing_or_stale'),1)
    def test_duplicate_id_is_rejected(self):
        with self.assertRaises(ValueError):summarize([{'id':'a','contract':'x'}],[{'id':'a'},{'id':'a'}])

    def test_declared_run_rejects_previous_or_missing_row_run_id(self):
        plan=[{'id':'a','contract':'same','run_id':'current'}]
        for row_run in ['previous',None]:
            with self.subTest(row_run=row_run):
                row={'id':'a','contract':'same','accepted':True,'evaluation':{'deliverable':True}}
                if row_run is not None:row['run_id']=row_run
                s=summarize(plan,[row])
                self.assertEqual(s['n'],1)
                self.assertEqual(s['missing_or_stale'],1)
                self.assertEqual(s['accepted'],0)
                self.assertEqual(s['deliverable'],0)
                self.assertEqual(s['deliverable_measured'],0)

    def test_matching_declared_run_counts_current_result(self):
        s=summarize([{'id':'a','contract':'x','run_id':'current'}],
                    [{'id':'a','contract':'x','run_id':'current','accepted':True,'evaluation':{'deliverable':True}}])
        self.assertEqual(s['recorded_current_contract'],1)
        self.assertEqual(s['deliverable'],1)

    def test_mixed_plan_run_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize([{'id':'a','contract':'x','run_id':'one'},
                       {'id':'b','contract':'y','run_id':'two'}],[])

    def test_partially_bound_plan_is_not_treated_as_legacy(self):
        with self.assertRaises(ValueError):
            summarize([{'id':'a','contract':'x','run_id':'one'},
                       {'id':'b','contract':'y'}],[])

    def test_legacy_plan_without_run_id_preserves_accepted_summary(self):
        s=summarize([{'id':'a','contract':'x'}],
                    [{'id':'a','contract':'x','accepted':True,'evaluation':{'deliverable':True}}])
        self.assertEqual(s['n'],1)
        self.assertEqual(s['missing_or_stale'],0)
        self.assertEqual(s['deliverable'],1)
        self.assertEqual(s['deliverable_measured'],1)

    def test_only_explicitly_accepted_rows_contribute_evaluation(self):
        metrics=['json_valid','schema_valid','business_correct','complete','deliverable']
        for accepted in [False,None,1]:
            with self.subTest(accepted=accepted):
                row={'id':'a','contract':'x','accepted':accepted,
                     'http_status':500,'transport_error':{'type':'TimeoutError'},
                     'evaluation':{key:True for key in metrics}}
                s=summarize([{'id':'a','contract':'x'}],[row])
                self.assertEqual(s['n'],1)
                self.assertEqual(s['recorded_current_contract'],1)
                self.assertEqual(s['transport_errors'],1)
                self.assertEqual(s['rejected'],int(accepted is False))
                for key in metrics:
                    self.assertEqual(s[key],0,key)
                    self.assertEqual(s[key+'_measured'],0,key)

    def test_accepted_false_evaluation_is_measured_but_not_success(self):
        s=summarize([{'id':'a','contract':'x'}],
                    [{'id':'a','contract':'x','accepted':True,'evaluation':{'deliverable':False}}])
        self.assertEqual(s['deliverable'],0)
        self.assertEqual(s['deliverable_measured'],1)

if __name__=='__main__':unittest.main()
