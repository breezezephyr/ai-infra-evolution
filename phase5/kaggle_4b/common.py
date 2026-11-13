"""Offline configuration, real sharded model identity and owned child supervision."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def weight_manifest(root):
    root = Path(root).resolve()
    index = root / 'model.safetensors.index.json'
    if index.exists():
        mapping = json.loads(index.read_text())['weight_map']
        if not mapping:
            raise ValueError('empty weight index')
        names = sorted(set(mapping.values()))
    else:
        names = sorted(p.name for p in root.glob('*.safetensors'))
    if not names:
        raise ValueError('no safetensors weights')
    shards = []
    for name in names:
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.safetensors'):
            raise ValueError('invalid shard path')
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('missing or empty weight shard: ' + name)
        shards.append(dict(path=name, bytes=path.stat().st_size, sha256=digest_file(path)))
    if set(names) != {p.name for p in root.glob('*.safetensors')}:
        raise ValueError('unindexed weight shards')
    return dict(schema=1, algorithm='sha256-canonical-shard-manifest-v1', shards=shards,
                sha256=hashlib.sha256(canonical(shards)).hexdigest())


def validate_manifest(manifest, root=None):
    try:
        shards = manifest['shards']
        names = [r['path'] for r in shards]
        good = (manifest['schema'] == 1 and manifest['algorithm'] == 'sha256-canonical-shard-manifest-v1'
                and bool(shards) and names == sorted(set(names))
                and all(Path(r['path']).name == r['path'] and r['path'].endswith('.safetensors')
                        and type(r['bytes']) is int and r['bytes'] > 0
                        and isinstance(r['sha256'], str) and len(r['sha256']) == 64
                        and all(c in '0123456789abcdef' for c in r['sha256']) for r in shards)
                and manifest['sha256'] == hashlib.sha256(canonical(shards)).hexdigest())
        return good and (root is None or manifest == weight_manifest(root))
    except (KeyError, TypeError, ValueError, OSError):
        return False


def identity_valid(identity):
    if not isinstance(identity, dict) or not isinstance(identity.get('files'), dict):
        return False
    m = identity.get('weight_manifest', {})
    files = identity.get('files', {})
    return (validate_manifest(m) and identity.get('weights_sha256') == m['sha256']
            and all(files.get(r['path']) == r['sha256'] for r in m['shards']))


PINNED_REVISION = '1cfa9a7208912126459214e8b04321603b3df60c'


def load_prepared(path):
    data = json.loads(Path(path).read_text())
    if data.get('repo') != 'Qwen/Qwen3-4B' or data.get('revision') != PINNED_REVISION:
        raise ValueError('prepared repo/revision must match pinned Qwen3-4B')
    root = Path(data['model_path']).expanduser().resolve()
    seen = set()
    for row in data['files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in seen:
            raise ValueError('unsafe or duplicate prepared file')
        seen.add(str(relative))
        file = root / relative
        if not file.is_file() or file.stat().st_size != row['bytes'] or digest_file(file) != row['sha256']:
            raise ValueError('prepared file mismatch: ' + str(relative))
    manifest = weight_manifest(root)
    if len(manifest['shards']) != 3 or not {r['path'] for r in manifest['shards']} <= seen:
        raise ValueError('prepared manifest must contain all three real weight shards')
    if 'model.safetensors.index.json' not in seen:
        raise ValueError('prepared manifest missing weight index')
    data['model_path'] = str(root)
    return data


def model_path():
    return Path(os.environ.get('P5_MODEL_PATH', '/kaggle/working/models/Qwen3-4B')).resolve()


def alias(n):
    return os.environ.get('P5_EXP%d_ALIAS' % n, 'exp%d-qwen3-4b' % n)


def model_identity():
    import platform
    import vllm
    import torch
    import transformers
    from transformers import AutoTokenizer
    root = model_path()
    config = json.loads((root / 'config.json').read_text())
    if config.get('model_type') != 'qwen3' or config.get('hidden_size') != 2560 or config.get('num_hidden_layers') != 36:
        raise ValueError('expected Qwen3 model')
    if vllm.__version__ != '0.8.5':
        raise RuntimeError('requires vLLM 0.8.5 V0')
    manifest = weight_manifest(root)
    if len(manifest['shards']) != 3:
        raise ValueError('Qwen3-4B must have three indexed shards')
    weight_hashes = {r['path']:r['sha256'] for r in manifest['shards']}
    files = {p.name: weight_hashes[p.name] if p.name in weight_hashes else digest_file(p) for p in sorted(root.iterdir()) if p.is_file()
             and (p.suffix in {'.json', '.safetensors', '.jinja', '.model', '.txt'})}
    for name in ['config.json', 'tokenizer.json', 'tokenizer_config.json']:
        if name not in files:
            raise ValueError('missing model identity file: ' + name)
    tok = AutoTokenizer.from_pretrained(str(root), local_files_only=True)
    return dict(model_path=str(root), model_revision=os.environ.get('P5_MODEL_REVISION'),
                weight_manifest=manifest, weights_sha256=manifest['sha256'], files=files,
                template_sha256=hashlib.sha256(tok.chat_template.encode()).hexdigest(),
                python=platform.python_version(), vllm=vllm.__version__, torch=torch.__version__,
                transformers=transformers.__version__, dtype='float16', cuda_visible_devices='0')


def backend_command(n, root=None):
    dtype = os.environ.get('P5_DTYPE', 'float16')
    if dtype not in ('float16', 'half'):
        raise ValueError('T4 suite requires FP16')
    util = float(os.environ.get('P5_GPU_UTIL', '0.85'))
    if not 0 < util < 1:
        raise ValueError('invalid GPU utilization')
    prefix = [os.environ['P5_VLLM_BIN']] if os.environ.get('P5_VLLM_BIN') else [sys.executable, '-m', 'vllm.entrypoints.cli.main']
    return prefix + ['serve', str(model_path()),
            '--served-model-name', alias(n), '--host', '127.0.0.1', '--port', str(8000 + n),
            '--dtype', dtype, '--tensor-parallel-size', '1', '--max-model-len', '2048',
            '--max-num-seqs', '4', '--max-num-batched-tokens', '4096',
            '--gpu-memory-utilization', str(util), '--enforce-eager',
            '--disable-frontend-multiprocessing', '--disable-log-requests',
            '--generation-config', 'vllm', '--middleware', 'backend_audit.AuditMiddleware']



def valid_backend_command(cmd, n, path, expected_alias=None):
    try:
        if not isinstance(cmd, list) or 'serve' not in cmd or not path:
            return False
        position = cmd.index('serve')
        if cmd[position+1] != path:
            return False
        flags = cmd[position+2:]
        expected = {'--served-model-name': expected_alias or alias(n), '--host':'127.0.0.1', '--port':str(8000+n),
                    '--tensor-parallel-size':'1', '--max-model-len':'2048', '--max-num-seqs':'4',
                    '--max-num-batched-tokens':'4096', '--generation-config':'vllm',
                    '--middleware':'backend_audit.AuditMiddleware'}
        for key, value in expected.items():
            if flags.count(key) != 1 or flags[flags.index(key)+1] != value:
                return False
        for flag in ['--enforce-eager','--disable-frontend-multiprocessing','--disable-log-requests']:
            if flags.count(flag) != 1:
                return False
        return (flags.count('--dtype') == 1 and flags[flags.index('--dtype')+1] in ('float16','half')
                and flags.count('--gpu-memory-utilization') == 1
                and 0 < float(flags[flags.index('--gpu-memory-utilization')+1]) < 1)
    except (ValueError, IndexError, TypeError):
        return False


def backend_env(n, code, root):
    return dict(os.environ, CUDA_VISIBLE_DEVICES='0', VLLM_USE_V1='0',
                PYTHONPATH=str(code), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                **{'EXP%d_AUDIT_PATH' % n: str(Path(root) / 'backend.jsonl')})


def gpu():
    try:
        return subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.used,utilization.gpu',
                                        '--format=csv,noheader'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def port_live(port):
    with socket.socket() as s:
        s.settimeout(.2)
        return s.connect_ex(('127.0.0.1', port)) == 0


def stop_owned(proc):
    """Only signal an unreaped direct child and its process group."""
    if proc is None or proc.returncode is not None:
        return
    if sys.platform == 'darwin' and child_exited(proc):
        # macOS can deny killpg on a zombie; GPU execution is Linux-only.
        proc.wait(timeout=10)
        return
    # Do not poll/reap first: the unreaped leader pins its process-group identity.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)



def child_exited(proc):
    # Non-reaping readiness probe. Keep the leader owned until stop_owned kills/reaps its group.
    if proc.returncode is not None:
        return True
    if hasattr(os, 'waitid'):
        return os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    # macOS CPU checks: ps observes state without waitpid/reaping. Kaggle uses waitid above.
    probe = subprocess.run(['ps', '-o', 'stat=', '-p', str(proc.pid)], capture_output=True, text=True)
    return probe.returncode != 0 or probe.stdout.strip().startswith('Z')


def install_signals():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal %s' % signum)
    signal.signal(signal.SIGTERM, interrupted)


def exec_frozen(command):
    os.execv(sys.executable, command)


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
