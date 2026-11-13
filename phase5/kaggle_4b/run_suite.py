#!/usr/bin/env python3
"""Run frozen exp25/26/27 sequentially, offline, never reuse an OUT directory."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

from common import (backend_command, backend_env, digest_file, dump, gpu,
                    install_signals, load_prepared, model_identity, port_live, stop_owned, child_exited)

BASE = Path(__file__).resolve().parent


def run_child(cmd, env, log):
    proc = None
    try:
        with Path(log).open('w') as stream:
            proc = subprocess.Popen(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            rc = proc.wait()
            if rc:
                raise RuntimeError('child failed (%s); see %s' % (rc, log))
    finally:
        stop_owned(proc)


def run_external_backend(n, root, env):
    """exp25/26 keep their existing backend/runner separation; own every child."""
    backend = None
    before = model_identity()
    dump(root / 'model-identity.json', before)
    cmd = backend_command(n)
    log = (root / 'backend-server.log').open('w')
    try:
        backend = subprocess.Popen(cmd, cwd=root, env=backend_env(n, root, root),
                                   stdout=log, stderr=log, start_new_session=True)
        dump(root / 'backend-startup.json', dict(pid=backend.pid, command=cmd,
             source_sha256={p.name: digest_file(p) for p in root.glob('*.py')},
             model_identity=before, gpu_before=gpu(), started_ns=time.monotonic_ns()))
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if child_exited(backend):
                raise RuntimeError('backend exited before ready')
            try:
                with urllib.request.urlopen('http://127.0.0.1:%d/health' % (8000+n), timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, TimeoutError):
                pass
            time.sleep(.2)
        else:
            raise TimeoutError('backend readiness timeout')
        cmd = [sys.executable, '-B', str(root / 'run.py'), '--out', str(root / 'formal')]
        if n == 25:
            cmd += ['--backend-pid', str(backend.pid)]
        else:
            cmd += ['--root', str(root)]
        run_child(cmd, env, root / 'runner.log')
    finally:
        stop_owned(backend)
        log.close()
        identity_error = None
        try:
            after = model_identity()
        except Exception as exc:
            after = {'files':{}, 'weight_manifest':None}
            identity_error = type(exc).__name__ + ': ' + str(exc)
        clean = dict(pid=backend.pid if backend else None,
                     exited=backend.poll() is not None if backend else True,
                     ports={str(p): port_live(p) for p in (8000+n, 8100+n)},
                     model_files_unchanged={k: after['files'].get(k) == v for k, v in before['files'].items()},
                     weight_manifest_unchanged=before['weight_manifest'] == after['weight_manifest'], gpu=gpu(),
                     identity_error=identity_error)
        dump(root / 'cleanup.json', clean)
        if not clean['exited'] or any(clean['ports'].values()) or not all(clean['model_files_unchanged'].values()):
            raise RuntimeError('backend cleanup/identity failed')


def snapshot(out):
    source = out / 'suite-source'
    source.mkdir()
    for p in [BASE / 'run_suite.py', BASE / 'common.py', BASE / 'source-provenance.json']:
        (source / p.name).write_bytes(p.read_bytes())
    for n in (25, 26, 27):
        dest = source / 'runtime' / ('exp%d' % n)
        dest.mkdir(parents=True)
        for p in (BASE / 'runtime' / dest.name).glob('*.py'):
            if not p.name.startswith('test_'):
                (dest / p.name).write_bytes(p.read_bytes())
    manifest = {str(p.relative_to(source)): digest_file(p) for p in sorted(source.rglob('*')) if p.is_file()}
    dump(out / 'suite-freeze.json', dict(source_sha256=manifest, created_ns=time.time_ns()))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    models = parser.add_mutually_exclusive_group(required=True)
    models.add_argument('--model', '--model-path', dest='model', type=Path, help='existing local Qwen3-4B snapshot')
    models.add_argument('--prepared', type=Path, help='bootstrap model-prepared.json; hashes rechecked offline')
    parser.add_argument('--python', type=Path, help='venv interpreter; re-exec before loading any ML library')
    parser.add_argument('--vllm-bin', type=Path, help='venv/bin/vllm')
    parser.add_argument('--model-revision', default=None, help='downloaded model revision; unknown remains null')
    parser.add_argument('--gpu-util', type=float, default=.85)
    args = parser.parse_args()
    if args.python:
        interpreter = os.path.abspath(os.path.expanduser(str(args.python)))
        if not Path(interpreter).is_file():
            parser.error('python interpreter does not exist')
        if os.path.abspath(sys.executable) != interpreter:
            os.execv(interpreter, [interpreter, '-B', str(Path(__file__).resolve()), *sys.argv[1:]])
    if args.vllm_bin:
        binary = os.path.abspath(os.path.expanduser(str(args.vllm_bin)))
        if not Path(binary).is_file() or not os.access(binary, os.X_OK):
            parser.error('vllm-bin must be an existing executable')
        os.environ['P5_VLLM_BIN'] = binary
    prepared = None
    out = args.out.expanduser().resolve()
    if out.exists():
        parser.error('OUT already exists; choose a new directory')
    # Refuse code-tree outputs: executable provenance must never become result data.
    if out == BASE or BASE in out.parents:
        parser.error('OUT must be independent of the code bundle')
    if args.prepared:
        prepared = load_prepared(args.prepared)
        args.model = Path(prepared['model_path'])
        args.model_revision = prepared['revision']
    if not args.model.expanduser().resolve().is_dir():
        parser.error('model must be an existing local directory')
    if not 0 < args.gpu_util < 1:
        parser.error('gpu-util must be between zero and one')
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(P5_MODEL_PATH=str(args.model.expanduser().resolve()),
                      P5_GPU_UTIL=str(args.gpu_util), P5_DTYPE='float16',
                      CUDA_VISIBLE_DEVICES='0', VLLM_USE_V1='0',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
    if args.model_revision:
        os.environ['P5_MODEL_REVISION'] = args.model_revision
    if prepared:
        dump(out / 'model-prepared.json', prepared)
    source = snapshot(out)
    frozen_config = {k: v for k, v in os.environ.items() if k in {
        'P5_MODEL_PATH', 'P5_GPU_UTIL', 'P5_DTYPE', 'P5_MODEL_REVISION', 'P5_VLLM_BIN', 'CUDA_VISIBLE_DEVICES', 'VLLM_USE_V1'}
        or k in {'P5_EXP25_ALIAS', 'P5_EXP26_ALIAS', 'P5_EXP27_ALIAS'}}
    frozen_config['python'] = sys.executable
    dump(out / 'suite-config.json', frozen_config)
    status = dict(accepted=False, experiments=[])
    install_signals()
    try:
        import torch
        import vllm
        if vllm.__version__ != '0.8.5' or not torch.cuda.is_available() or 'T4' not in torch.cuda.get_device_name(0):
            raise RuntimeError('requires vLLM 0.8.5 and CUDA GPU0 T4')
        for n in (25, 26, 27):
            for p in (8000+n, 8100+n):
                if port_live(p):
                    raise RuntimeError('port %d already occupied; no existing service will be stopped' % p)
            root = out / ('exp%d' % n)
            root.mkdir()
            for p in (source / 'runtime' / root.name).glob('*.py'):
                (root / p.name).write_bytes(p.read_bytes())
            env = dict(os.environ, P5_EXP_ROOT=str(root))
            if n in (25, 26):
                # backend_env is constructed in this process too.
                os.environ['P5_EXP_ROOT'] = str(root)
                run_external_backend(n, root, env)
            else:
                run_child([sys.executable, '-B', str(root / 'run.py'), '--out', str(root / 'formal')],
                          env, root / 'runner.log')
            formal = root / 'formal'
            # Explicit final independent native analysis; no CPU fixture profile.
            run_child([sys.executable, '-B', str(formal / 'code' / 'analyze.py'), '--out', str(formal)],
                      env, root / 'final-analysis.log')
            summary = json.loads((formal / 'summary.json').read_text())
            if summary.get('accepted') is not True:
                raise RuntimeError('native analyzer rejected exp%d' % n)
            status['experiments'].append(dict(experiment=n, accepted=True, planned=summary['planned'],
                                               summary=str(formal / 'summary.json')))
            dump(out / 'suite-summary.json', status)
        status['accepted'] = True
    except BaseException as exc:
        status['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        dump(out / 'suite-summary.json', status)


if __name__ == '__main__':
    main()
