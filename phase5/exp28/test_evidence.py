"""CPU-only checks for false acceptance, duplicate dispatch, and secret capture."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
import base64
import json
import sys
from PIL import Image
import run

def response(size=(512,512)):
    stream=BytesIO()
    Image.new('RGB',size,'red').save(stream,format='PNG')
    return dict(model=run.PAYLOAD['model'],generation={
        'size':'512x512','steps':8,'seed':20261109,'elapsed_seconds':1.0},
        data=[{'revised_prompt':run.PROMPT,'b64_json':base64.b64encode(stream.getvalue()).decode()}])

class HTTPResponse(BytesIO):
    def __init__(self, body, status=404):
        super().__init__(body)
        self.code=status
        self.headers={'Content-Type':'text/html'}

class EvidenceChecks(TestCase):
    def test_valid_png_has_equal_readback(self):
        with TemporaryDirectory() as tmp:
            result=run.validate_image(response(),run.PAYLOAD,Path(tmp)/'image.png')
            self.assertEqual(result['decoded_sha256'],result['disk_readback_sha256'])
            self.assertTrue(result['full_byte_readback_equal'])

    def test_wrong_dimensions_rejected(self):
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run.validate_image(response((256,512)),run.PAYLOAD,Path(tmp)/'image.png')

    def test_corrupt_png_rejected(self):
        result=response(); raw=bytearray(base64.b64decode(result['data'][0]['b64_json']))
        raw[16]^=1
        result['data'][0]['b64_json']=base64.b64encode(raw).decode()
        with TemporaryDirectory() as tmp, self.assertRaises(Exception):
            run.validate_image(result,run.PAYLOAD,Path(tmp)/'image.png')

    def test_invalid_base64_rejected(self):
        result=response(); result['data'][0]['b64_json']='not base64!!!'
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run.validate_image(result,run.PAYLOAD,Path(tmp)/'image.png')

    def test_wrong_seed_rejected(self):
        result=response(); result['generation']['seed']=42
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run.validate_image(result,run.PAYLOAD,Path(tmp)/'image.png')

    def test_missing_elapsed_rejected(self):
        result=response(); del result['generation']['elapsed_seconds']
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run.validate_image(result,run.PAYLOAD,Path(tmp)/'image.png')

    def test_untrusted_origins_and_embedded_secrets_rejected(self):
        for url in ['https://temporary-api.example.invalid','https://example.com','https://temporary-api.example.invalid',
                    'https://temporary-api.example.invalid?key=REDACTED','https://temporary-api.example.invalid/v1']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                run.check_endpoint(url)

    def test_http_redirects_disabled(self):
        self.assertIsNone(run.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.test'))

    def test_failed_health_cannot_submit_generation(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'run'; config=Path(tmp)/'private.json'
            config.write_text(json.dumps({'base_url':'https://temporary-api.example.invalid','api_key':'this-is-a-cpu-test-key-only'})); config.chmod(0o600)
            opener=mock.Mock(); opener.open.return_value=HTTPResponse(b'No interface is running')
            with mock.patch.object(sys,'argv',['run.py','--run-dir',str(root),'--config',str(config),'--execute']), mock.patch.object(run.urllib.request,'build_opener',return_value=opener):
                self.assertEqual(run.main(),75)
            self.assertEqual(opener.open.call_count,1)
            summary=json.loads((root/'summary.json').read_text())
            self.assertEqual(summary['valid_generation_http_dispatch_attempts'],0)
            self.assertEqual(summary['image_endpoint_http_dispatch_attempts'],0)
            self.assertFalse(summary['api_contract_and_delivery_passed'])

    def test_submitted_generation_cannot_be_retried(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'dispatch-state.json').write_text('{"valid_generation_submitted":1}')
            with mock.patch.object(sys,'argv',['run.py','--run-dir',str(root),'--execute']), self.assertRaises(SystemExit):
                run.main()

    def test_reflected_credential_not_persisted(self):
        with TemporaryDirectory() as tmp:
            secret='this-is-a-cpu-test-key-only'
            runner=run.Runner(Path(tmp),{'base_url':'https://temporary-api.example.invalid','api_key':secret})
            runner.opener=mock.Mock(); runner.opener.open.return_value=HTTPResponse(secret.encode())
            row,_,stage=runner.request('probe','/health')
            self.assertIsNone(row['status'])
            self.assertFalse((stage/'response-body.raw').exists())
            self.assertNotIn(secret,(stage/'response-metadata.json').read_text())

    def test_reflected_header_credential_not_persisted(self):
        with TemporaryDirectory() as tmp:
            secret='this-is-a-cpu-test-key-only'
            runner=run.Runner(Path(tmp),{'base_url':'https://temporary-api.example.invalid','api_key':secret})
            result=HTTPResponse(b'not ready'); result.headers={'X-Request-ID':secret}
            runner.opener=mock.Mock(); runner.opener.open.return_value=result
            _,_,stage=runner.request('probe','/health')
            self.assertNotIn(secret,(stage/'response-metadata.json').read_text())

    def test_json_escaped_credential_not_persisted(self):
        with TemporaryDirectory() as tmp:
            secret='this-is-a-cpu-test-key-only'
            runner=run.Runner(Path(tmp),{'base_url':'https://temporary-api.example.invalid','api_key':secret})
            raw=json.dumps({'key':secret}).replace('this','\\u0074his').encode()
            self.assertNotIn(secret.encode(),raw)
            runner.opener=mock.Mock(); runner.opener.open.return_value=HTTPResponse(raw)
            row,_,stage=runner.request('probe','/health')
            self.assertIsNone(row['status'])
            self.assertFalse((stage/'response-body.raw').exists())
            self.assertFalse((stage/'response.json').exists())

    def test_reserved_marker_not_counted_as_http_attempt(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'dispatch-state.json').write_text('{"valid_generation_dispatch_reserved":1}')
            (root/'requests/R04-real-image').mkdir(parents=True)
            runner=run.Runner(root,{'base_url':'https://temporary-api.example.invalid','api_key':'this-is-a-cpu-test-key-only'})
            runner.opener=mock.Mock()
            with self.assertRaises(FileExistsError):
                runner.request('R04-real-image','/v1/images/generations',run.PAYLOAD)
            summary=runner.finish('case_failed','dispatch never reached')
            self.assertEqual(summary['valid_generation_dispatch_reserved'],1)
            self.assertEqual(summary['valid_generation_http_dispatch_attempts'],0)
            self.assertEqual(summary['image_endpoint_http_dispatch_attempts'],0)
            runner.opener.open.assert_not_called()

    def test_previous_failure_summary_preserved_exactly(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); old=b'{"state":"preflight_unavailable","requests":[]}\n'
            (root/'summary.json').write_bytes(old)
            runner=run.Runner(root,{'base_url':'https://temporary-api.example.invalid','api_key':'this-is-a-cpu-test-key-only'})
            runner.finish('preflight_ready','later invocation')
            self.assertEqual((root/'summary-history'/(run.digest(old)+'.json')).read_bytes(),old)

if __name__=='__main__':
    main()
