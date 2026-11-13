"""Offline checks; all test scratch/evidence stays below this code directory."""
import ast
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent
TMP = BASE / 'checks-tmp'


def check_static():
    sources = list(BASE.glob('*.py')) + list((BASE / 'runtime').rglob('*.py')) + list((BASE / 'tests').glob('*.py'))
    for path in sources:
        ast.parse(path.read_text(), filename=str(path))
        if 'runtime' in path.parts and not path.name.startswith('test_'):
            text = path.read_text()
            for old in ('/opt/', '/root/vllm-env', '0.6b', '0.6B', 'bfloat16'):
                assert old not in text, (path, old)
    for n in (25, 26, 27):
        assert (BASE / 'runtime' / ('exp%d' % n) / 'common.py').read_bytes() == (BASE / 'common.py').read_bytes()
    original = json.loads((BASE / 'source-provenance.json').read_text())
    for n in (26, 27):
        rel = 'phase5/exp%d/backend_audit.py' % n
        copied = BASE / 'runtime' / ('exp%d' % n) / 'backend_audit.py'
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == original[rel], 'native hooks changed'
    # When running in the original checkout, prove the old source files are unchanged.
    originals = BASE.parent.parent
    checked = 0
    for rel, expected in original.items():
        path = originals / rel
        if path.exists():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'original changed: ' + rel
            checked += 1
    print('static: %d Python files; native hooks exact copies; %d original source hashes unchanged' % (len(sources), checked), flush=True)


def check_plain_functions():
    """Run unparametrized exp25 gateway CPU tests with real httpx ASGI transport."""
    directory = BASE / 'runtime' / 'exp25'
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location('gateway_cpu_checks', directory / 'test_gateway.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        count = 0
        for name, fn in vars(module).items():
            if not name.startswith('test_') or not callable(fn):
                continue
            params = list(inspect.signature(fn).parameters)
            if params not in ([], ['tmp_path']):
                raise AssertionError('unhandled fixture: ' + name)
            with tempfile.TemporaryDirectory(dir=TMP) as td:
                fn(Path(td)) if params else fn()
            count += 1
        print('exp25 gateway CPU: %d passed' % count, flush=True)
    finally:
        sys.path.pop(0)


def main():
    TMP.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(TMP))
    check_static()
    subprocess.run([sys.executable, '-B', str(BASE / 'tests' / 'test_port.py')], env=env, check=True)
    for n in (26, 27):
        subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s',
                        str(BASE / 'runtime' / ('exp%d' % n)), '-p', 'test_analyze.py', '-q'], env=env, check=True)
    if importlib.util.find_spec("fastapi") is not None:
        check_plain_functions()
    else:
        print("SKIP exp25 gateway CPU tests: fastapi is not installed", flush=True)
    print('Required static/CPU checks passed; optional dependency skips are listed above. No GPU/download/install.', flush=True)


if __name__ == '__main__':
    main()
