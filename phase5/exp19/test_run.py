import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import run
from run import run_case, compare_families


class NativeBoundaryTests(unittest.TestCase):
    def test_native_enum_in_raw_conversion_is_json_serializable(self):
        case=dict(id='native-json',protocol='chat',family='text',input={
            'model':'DeepSeek-V4.1-Flash','messages':[{'role':'user','content':'hello'}]},
            options={},expect={'conversion':'ok','facts':{}},checks=['convert','assert_facts','render'])
        row=run_case(case,{})
        encoded=json.dumps(row,ensure_ascii=False)
        self.assertIn('ThinkingInitialStage',encoded)
        self.assertEqual(row['conversion']['status'],'ok')

    def test_export_failure_is_not_a_request_conversion_rejection(self):
        case=dict(id='observer',protocol='chat',family='text',input={
            'model':'DeepSeek-V4.1-Flash','messages':[{'role':'user','content':'hello'}]},
            options={},expect={'conversion':'ok','facts':{}},checks=['convert','assert_facts'])
        with patch('run.snapshot',side_effect=RuntimeError('observer failed')):
            row=run_case(case,{})
        self.assertEqual(row['conversion']['status'],'ok')
        self.assertEqual(next(c['status'] for c in row['checks'] if c['name']=='assert_facts'),'fail')

    def test_unexpected_rejection_preserves_family_record_instead_of_crashing(self):
        base=dict(protocol='chat',family='same',options={},expect={'conversion':'ok','facts':{'thinking_mode':True}},
                  checks=['convert','assert_facts','render','family_compare'])
        cases=[dict(base,id='ok',input={'model':'DeepSeek-V4.1-Flash','messages':[{'role':'user','content':'hello'}]}),
               dict(base,id='bad',input={'model':'unknown','messages':[{'role':'user','content':'hello'}]})]
        rows=[run_case(c,{}) for c in cases]
        report=compare_families(cases,rows)
        self.assertFalse(report[0]['passed'])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['conversion']['status'],'error')
        self.assertEqual(next(c['status'] for c in rows[1]['checks'] if c['name']=='family_compare'),'fail')

    def test_wrong_version_tokenizer_rejected_before_use(self):
        p=Path(__file__).resolve().parents[1]/'vendor/minimal/static/tokenizers/v41/tokenizer.json'
        with self.assertRaisesRegex(ValueError,'hash'):
            run.verified_tokenizer(p,'v4')

    def test_lost_literal_is_check_failure_without_erasing_conversion(self):
        case=next(c for c in json.loads((Path(__file__).parent/'cases.json').read_text())['cases']
                  if c['family']=='special_user_literal' and c['protocol']=='chat')
        tokenizer=run.recipe.Tokenizer.from_file(str(Path(__file__).resolve().parents[1]/'vendor/minimal/static/tokenizers/v41/tokenizer.json'))
        real=run.recipe.DeepseekV41Encoding()
        observer=SimpleNamespace(render_conversation=lambda _:SimpleNamespace(prompt='observer lost literal',special_ranges=[]),
                                 with_tokenizer=real.with_tokenizer)
        with patch.dict(run.ENCODING,{'v41':lambda:observer}):
            row=run_case(case,{'v41':tokenizer})
        self.assertEqual(row['conversion']['status'],'ok')
        self.assertIn('facts',row)
        self.assertEqual(next(c['status'] for c in row['checks'] if c['name']=='literal_special_ranges_excluded'),'fail')


if __name__=='__main__':unittest.main()
