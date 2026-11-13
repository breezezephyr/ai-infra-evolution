"""Exercise the real runner's plan and persistence with a test HTTP boundary."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import gpu_run


class GpuRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir()
        for name in ['gpu_run.py','evaluate.py','backend_audit.py']:
            shutil.copyfile(gpu_run.ROOT/name,self.source/name)
        fixture={'seeds':[17],'generation':{'temperature':0.6,'top_p':0.9,'max_tokens':192},
                 'cases':[{'id':'unit','family':'arithmetic','task':'计算1+2，填写n。',
                           'schema':{'type':'object','properties':{'n':{'type':'integer'}},
                                     'required':['n'],'additionalProperties':False},'expected':{'n':3}}]}
        (self.source/'gpu-cases.json').write_text(json.dumps(fixture))

    def run_recording(self,run_id,open_response):
        out=self.root/run_id
        argv=['gpu_run.py','--base-url','http://unit.invalid','--model','unit-model',
              '--out',str(out),'--run-id',run_id]
        with patch.object(gpu_run,'ROOT',self.source),patch('sys.argv',argv), \
             patch.object(gpu_run.urllib.request,'urlopen',side_effect=open_response), \
             contextlib.redirect_stdout(io.StringIO()):
            gpu_run.main()
        return (json.loads((out/'plan.json').read_text()),
                json.loads((out/'records.json').read_text())['records'],
                json.loads((out/'summary.json').read_text()))

    def successful_response(self,request,timeout):
        body={'id':'unit-response','object':'chat.completion','created':0,'model':'unit-model',
              'choices':[{'index':0,'message':{'role':'assistant','content':'{"n":3}'},
                          'finish_reason':'stop'}],
              'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}}
        response=io.BytesIO(json.dumps(body).encode());response.status=200
        return response

    def test_every_job_and_persisted_row_bind_run_and_contract(self):
        first,rows,report=self.run_recording('run-one',self.successful_response)
        second,other_rows,other_report=self.run_recording('run-two',self.successful_response)
        self.assertEqual(len(first),3);self.assertEqual(len(rows),3)
        self.assertEqual(report['overall']['deliverable'],3)
        self.assertEqual(other_report['overall']['deliverable'],3)
        for job,row,new_job,new_row in zip(first,rows,second,other_rows):
            self.assertEqual(job.get('run_id'),'run-one')
            self.assertEqual(row.get('run_id'),'run-one')
            self.assertEqual(new_job.get('run_id'),'run-two')
            self.assertEqual(new_row.get('run_id'),'run-two')
            self.assertEqual(job['contract'],row['contract'])
            self.assertEqual(new_job['contract'],new_row['contract'])
            self.assertNotEqual(job['contract'],new_job['contract'])
            self.assertEqual(job['payload'],new_job['payload'])
            self.assertEqual(row['payload_sha256'],new_row['payload_sha256'])

    def test_http_error_invalid_utf8_is_persisted_and_remaining_jobs_continue(self):
        def fail(request,timeout):
            raise urllib.error.HTTPError(request.full_url,500,'bad gateway',{},
                                         io.BytesIO(b'upstream \xff failure'))
        plan,rows,report=self.run_recording('bad-utf8',fail)
        self.assertEqual(len(plan),3);self.assertEqual(len(rows),3)
        self.assertEqual(report['overall']['n'],3)
        self.assertEqual(report['overall']['rejected'],3)
        self.assertEqual(report['overall']['transport_errors'],0)
        self.assertEqual(report['overall']['deliverable_measured'],0)
        for row in rows:
            self.assertIs(row['accepted'],False)
            self.assertEqual(row['http_status'],500)
            self.assertEqual(row['error_body'],'upstream \ufffd failure')

    def test_http_error_valid_utf8_preserves_original_message(self):
        def fail(request,timeout):
            raise urllib.error.HTTPError(request.full_url,400,'bad request',{},
                                         io.BytesIO('错误：不支持'.encode()))
        _,rows,report=self.run_recording('valid-utf8',fail)
        self.assertEqual(report['overall']['rejected'],3)
        self.assertTrue(all(row['error_body']=='错误：不支持' for row in rows))


if __name__=='__main__':unittest.main()
