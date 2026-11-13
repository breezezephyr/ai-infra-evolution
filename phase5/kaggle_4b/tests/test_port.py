import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_shards_identity_detects_mutation_and_no_fake_weight(tmp_path):
    from common import weight_manifest, validate_manifest
    for name, data in {'model-00001-of-00002.safetensors': b'a', 'model-00002-of-00002.safetensors': b'b'}.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a': 'model-00001-of-00002.safetensors', 'b': 'model-00002-of-00002.safetensors'}}))
    manifest = weight_manifest(tmp_path)
    assert len(manifest['shards']) == 2
    assert validate_manifest(manifest, tmp_path)
    assert not (tmp_path / 'model.safetensors').exists()
    (tmp_path / 'model-00002-of-00002.safetensors').write_bytes(b'changed')
    assert not validate_manifest(manifest, tmp_path)


def test_missing_shard_rejected(tmp_path):
    from common import weight_manifest
    import unittest
    (tmp_path / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a': 'missing.safetensors'}}))
    with unittest.TestCase().assertRaises((ValueError, FileNotFoundError)):
        weight_manifest(tmp_path)


def test_command_is_v0_fp16_gpu0_and_original_ports(tmp_path):
    from common import backend_command, backend_env
    cmd = backend_command(26, tmp_path)
    assert cmd[:3] == [sys.executable, '-m', 'vllm.entrypoints.cli.main']
    for flag, value in [('--dtype', 'float16'), ('--gpu-memory-utilization', '0.85'), ('--port', '8026'), ('--tensor-parallel-size', '1')]:
        assert cmd[cmd.index(flag) + 1] == value
    env = backend_env(26, tmp_path, tmp_path)
    assert env['CUDA_VISIBLE_DEVICES'] == '0'
    assert env['VLLM_USE_V1'] == '0'
    assert '0.6' not in ' '.join(cmd)


def test_suite_refuses_existing_output(tmp_path):
    p = subprocess.run([sys.executable, '-B', str(ROOT / 'run_suite.py'), '--out', str(tmp_path), '--model', str(tmp_path)], capture_output=True, text=True)
    assert p.returncode != 0
    assert 'exist' in p.stderr.lower()
    assert list(tmp_path.iterdir()) == []


def test_plans_keep_denominators():
    import importlib.util
    for n, filename, count in [(25, 'run.py', 42), (26, 'gateway.py', 17), (27, 'plan.py', 42)]:
        directory = ROOT / 'runtime' / ('exp' + str(n))
        sys.path.insert(0, str(directory))
        try:
            spec = importlib.util.spec_from_file_location('plan_probe_' + str(n), directory / filename)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            assert len(mod.make_plan()['cases']) == count
        finally:
            sys.path.pop(0)



def test_prepared_pins_revision_and_checks_all_three_shards(tmp_path):
    from common import load_prepared, digest_file
    from unittest import TestCase
    names = ['model-%05d-of-00003.safetensors' % i for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    (tmp_path / 'model.safetensors.index.json').write_text(json.dumps({'weight_map':dict(zip('abc', names))}))
    files = [dict(path=p.name, bytes=p.stat().st_size, sha256=digest_file(p)) for p in tmp_path.iterdir()]
    prepared = tmp_path / 'model-prepared.json'
    data = dict(repo='Qwen/Qwen3-4B', revision='1cfa9a7208912126459214e8b04321603b3df60c', model_path=str(tmp_path), files=files, packages={})
    prepared.write_text(json.dumps(data))
    assert load_prepared(prepared)['model_path'] == str(tmp_path)
    (tmp_path / names[0]).write_bytes(b'corrupt')
    with TestCase().assertRaises(ValueError):
        load_prepared(prepared)
    data['revision'] = 'wrong'
    prepared.write_text(json.dumps(data))
    with TestCase().assertRaises(ValueError):
        load_prepared(prepared)


def test_explicit_vllm_binary_is_used(tmp_path):
    from common import backend_command
    from unittest.mock import patch
    with patch.dict(os.environ, {'P5_VLLM_BIN':'/kaggle/temp/p5-4b/venv311/bin/vllm'}):
        cmd = backend_command(25)
        assert cmd[:2] == ['/kaggle/temp/p5-4b/venv311/bin/vllm', 'serve']


def test_stop_owned_preserves_unrelated_process(tmp_path):
    from common import stop_owned
    import time
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    try:
        stop_owned(owned)
        assert owned.returncode is not None
        assert other.poll() is None
    finally:
        stop_owned(other)


def test_child_failure_keeps_log_and_raises(tmp_path):
    from run_suite import run_child
    from unittest import TestCase
    log = tmp_path / 'failed-child.log'
    with TestCase().assertRaises(RuntimeError):
        run_child([sys.executable, '-c', 'print("raw preserved", flush=True); raise SystemExit(7)'], dict(os.environ), log)
    assert 'raw preserved' in log.read_text()


def test_backend_command_validation_rejects_wrong_dtype_and_port(tmp_path):
    from common import backend_command, valid_backend_command, model_path
    cmd = backend_command(27)
    assert valid_backend_command(cmd, 27, str(model_path()))
    cmd[cmd.index('--dtype')+1] = 'bfloat16'
    assert not valid_backend_command(cmd, 27, str(model_path()))
    cmd = backend_command(27)
    cmd[cmd.index('--port')+1] = '8000'
    assert not valid_backend_command(cmd, 27, str(model_path()))


def test_identity_validation_fails_closed_on_non_object(tmp_path):
    from common import identity_valid
    assert not identity_valid(None)
    assert not identity_valid([])


def test_readiness_probe_does_not_reap_child(tmp_path):
    from common import child_exited, stop_owned
    import time
    child = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(3)'], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not child_exited(child):
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert child.returncode is None
    finally:
        stop_owned(child)
    assert child.returncode == 3

if __name__ == '__main__':
    import inspect
    import tempfile
    import traceback
    (ROOT / 'checks-tmp').mkdir(exist_ok=True)
    failures = 0
    for name, fn in list(globals().items()):
        if not name.startswith('test_') or not callable(fn):
            continue
        try:
            with tempfile.TemporaryDirectory(dir=ROOT / 'checks-tmp') as td:
                fn(Path(td)) if inspect.signature(fn).parameters else fn()
            print('PASS', name)
        except Exception:
            failures += 1
            print('FAIL', name)
            traceback.print_exc()
    raise SystemExit(bool(failures))
