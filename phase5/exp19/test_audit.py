from copy import deepcopy
import unittest
from audit import assess, summarize, identity, fact_equal


class AuditTests(unittest.TestCase):
    def test_expected_rejection_is_not_a_successful_conversion(self):
        case={'id':'reject','protocol':'chat','family':'bad','expect':{'conversion':'error'},'checks':['convert']}
        row={'id':'reject','contract_sha256':identity(case),'conversion':{'status':'error','stage':'convert'},
             'checks':[{'name':'convert','status':'pass'}]}
        result=summarize([case],[row])
        self.assertEqual(result['expected_rejections'],1)
        self.assertEqual(result['accepted'],0)
        self.assertEqual(result['conformant'],1)

    def test_encoding_failure_cannot_satisfy_expected_conversion_rejection(self):
        case={'id':'x','expect':{'conversion':'error'},'checks':['convert']}
        row={'id':'x','contract_sha256':identity(case),'conversion':{'status':'ok'},'checks':[{'name':'convert','status':'pass'}],
             'encoding':{'status':'error'}}
        self.assertEqual(assess(case,row)['status'],'fail')

    def test_missing_row_and_check_stay_in_denominator(self):
        cases=[{'id':i,'protocol':'chat','family':'a','expect':{'conversion':'ok'},'checks':['convert','encode']} for i in ['a','b']]
        rows=[{'id':'a','contract_sha256':identity(cases[0]),'conversion':{'status':'ok'},
               'checks':[{'name':'convert','status':'pass'}]}]
        result=summarize(cases,rows)
        self.assertEqual((result['n'],result['conformant'],result['unknown']), (2,0,2))
        self.assertEqual(result['requested_check_count'],4)
        self.assertEqual(result['check_counts']['unknown'],3)

    def test_duplicate_results_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            summarize([], [{'id':'a'},{'id':'a'}])

    def test_changed_contract_cannot_reuse_old_checks(self):
        case={'id':'contract','protocol':'chat','family':'text',
              'input':{'model':'DeepSeek-V4.1-Flash','messages':[{'role':'user','content':'hello'}]},
              'options':{},'expect':{'conversion':'ok','facts':{'temperature':1}},
              'checks':['convert','assert_facts']}
        row={'id':case['id'],'contract_sha256':identity(case),'conversion':{'status':'ok'},
             'facts':{'temperature':1},
             'checks':[{'name':name,'status':'pass'} for name in case['checks']]}
        self.assertEqual(assess(case,row)['status'],'pass')
        changes={
            'expect':{'conversion':'ok','facts':{'temperature':0.75}},
            'input':{'model':'DeepSeek-V4.1-Flash','messages':[{'role':'user','content':'changed'}]},
            'options':{'alias':{'name':'deepseek-chat','version':'v4'}},
            'protocol':'responses',
            'checks':['convert','assert_facts','render'],
            'family':'changed_family',
        }
        for field,value in changes.items():
            with self.subTest(field=field):
                changed=deepcopy(case);changed[field]=value
                self.assertEqual(assess(changed,row)['status'],'unknown')
                result=summarize([changed],[row])
                self.assertEqual((result['accepted'],result['conformant'],result['unknown']),(0,0,1))
                self.assertEqual(result.get('unverified'),1)
                self.assertEqual(result['check_counts'],{'pass':0,'fail':0,'unknown':len(changed['checks'])})

    def test_unverified_records_do_not_affect_current_statistics(self):
        cases=[];rows=[]
        for name,conversion,verification in [
            ('verified-ok','ok','match'),('verified-error','error','match'),
            ('stale-ok','ok','mismatch'),('stale-error','error','mismatch'),
            ('unsigned-ok','ok','missing'),('unsigned-error','error','missing'),
            ('absent','ok','absent'),
        ]:
            case={'id':name,'protocol':'chat','family':'text','input':{'text':'current'},'options':{},
                  'expect':{'conversion':conversion},'checks':['convert']}
            cases.append(case)
            if verification=='absent':continue
            row={'id':name,'conversion':{'status':conversion},'checks':[{'name':'convert','status':'pass'}]}
            if verification=='match':row['contract_sha256']=identity(case)
            elif verification=='mismatch':row['contract_sha256']=identity({**case,'input':{'text':'old'}})
            rows.append(row)
        result=summarize(cases,rows)
        self.assertEqual(result.get('unverified'),4)
        self.assertEqual((result['n'],result['accepted'],result['rejected'],result['expected_rejections']),(7,1,1,1))
        self.assertEqual((result['conformant'],result['failed'],result['unknown']),(2,0,5))
        self.assertEqual(result['requested_check_count'],7)
        self.assertEqual(result['check_counts'],{'pass':2,'fail':0,'unknown':5})

    def test_missing_or_mismatched_contract_ignores_stale_failures(self):
        case={'id':'stale','expect':{'conversion':'ok'},'checks':['convert']}
        for digest in [None,'0'*64]:
            with self.subTest(contract_sha256=digest):
                row={'id':'stale','conversion':{'status':'error'},'checks':[{'name':'convert','status':'fail'}]}
                if digest is not None:row['contract_sha256']=digest
                self.assertEqual(assess(case,row)['status'],'unknown')
                result=summarize([case],[row])
                self.assertEqual((result['rejected'],result['failed'],result['unknown']),(0,0,1))
                self.assertEqual(result['check_counts'],{'pass':0,'fail':0,'unknown':1})

    def test_duplicate_result_check_names_are_rejected(self):
        case={'id':'duplicate','expect':{'conversion':'ok'},'checks':['convert']}
        for statuses in [('fail','pass'),('pass','fail')]:
            with self.subTest(statuses=statuses):
                row={'id':case['id'],'contract_sha256':identity(case),'conversion':{'status':'ok'},
                     'checks':[{'name':'convert','status':status} for status in statuses]}
                with self.assertRaisesRegex(ValueError,'duplicate.*check'):
                    assess(case,row)
                with self.assertRaisesRegex(ValueError,'duplicate.*check'):
                    summarize([case],[row])

    def test_duplicate_fixture_check_names_are_rejected(self):
        case={'id':'duplicate','expect':{'conversion':'ok'},'checks':['convert','convert']}
        row={'id':case['id'],'contract_sha256':identity(case),'conversion':{'status':'ok'},
             'checks':[{'name':'convert','status':'pass'}]}
        with self.assertRaisesRegex(ValueError,'duplicate.*check'):
            assess(case,row)
        with self.assertRaisesRegex(ValueError,'duplicate.*check'):
            summarize([case],[row])

    def test_false_null_and_zero_are_not_missing_values(self):
        self.assertNotEqual(identity({'a':None}),identity({'a':False}))
        self.assertNotEqual(identity({'a':False}),identity({'a':0}))
        self.assertEqual(identity({'b':1,'a':'x'}),identity({'a':'x','b':1}))

    def test_fact_comparison_rejects_bool_numeric_coercion(self):
        self.assertFalse(fact_equal(False,0))
        self.assertFalse(fact_equal([True],[1]))
        self.assertTrue(fact_equal(.95000001,.95))
        self.assertTrue(fact_equal(None,None))
        self.assertFalse(fact_equal(None,False))


if __name__=='__main__':unittest.main()
