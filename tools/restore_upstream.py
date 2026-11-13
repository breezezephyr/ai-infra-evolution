#!/usr/bin/env python3
"""只恢复经固定哈希验证的上游文件；默认不联网、不写文件。"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HOSTS = frozenset({'raw.githubusercontent.com', 'github.com', 'api.github.com'})
MAX_BYTES = 64 * 1024 * 1024


def checked_url(url):
    if not isinstance(url, str) or not url.isascii() or any(ord(c) <= 32 for c in url):
        raise ValueError('URL 必须为无空白的 ASCII HTTPS 地址')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc not in HOSTS
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or '?' in url or '#' in url):
        raise ValueError('URL 不符合 HTTPS allowlist 或带有认证/query/fragment')
    segments = unquote(parsed.path).split('/')
    if any(p in {'.', '..'} for p in segments) or '\\' in unquote(parsed.path):
        raise ValueError('URL 路径不安全')
    if not any(re.fullmatch(r'[0-9a-f]{40}', p) for p in segments):
        raise ValueError('URL 必须包含完整固定 commit SHA')
    return url


def checked_path(value):
    if not isinstance(value, str) or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('目标路径格式不合法')
    parts = value.split('/')
    if (len(parts) < 3 or parts[:2] != ['phase5', 'vendor']
            or any(p in {'', '.', '..'} for p in parts)
            or PurePosixPath(value).is_absolute()):
        raise ValueError('目标路径必须位于 phase5/vendor 内，且不能含 traversal')
    if value.lower().endswith(('.whl', '.so', '.dylib', '.dll', '.safetensors', '.pt', '.pth', '.gguf')):
        raise ValueError('不恢复 wheel、原生二进制或权重')
    return parts


def checked_source(value):
    if (not isinstance(value, str) or '\\' in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError('本地 metadata 路径不合法')
    parts = value.split('/')
    if (len(parts) < 3 or parts[:2] != ['tools', 'upstream-metadata']
            or any(p in {'', '.', '..'} for p in parts) or not value.endswith('.json')):
        raise ValueError('本地来源必须位于 tools/upstream-metadata 内')
    return parts


def load_manifest(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or not isinstance(data.get('files'), list)
            or not isinstance(data.get('local_metadata', []), list)):
        raise ValueError('恢复清单版本或 files 不合法')
    seen = set()
    for item in data['files']:
        if not isinstance(item, dict) or 'source' in item:
            raise ValueError('网络条目不能包含本地来源')
        checked_url(item['url'])
    for item in data.get('local_metadata', []):
        if not isinstance(item, dict) or 'url' in item:
            raise ValueError('本地 metadata 不能包含 URL')
        checked_source(item['source'])
    items = data['files'] + data.get('local_metadata', [])
    for item in items:
        checked_path(item['path'])
        if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('必须固定 SHA-256')
        if type(item['bytes']) is not int or not 0 <= item['bytes'] <= MAX_BYTES:
            raise ValueError('bytes 不合法或超过大小上限')
        if item['path'] in seen:
            raise ValueError('清单存在重复目标路径')
        seen.add(item['path'])
    return items


@contextlib.contextmanager
def parent_fd(root, parts, create=False):
    """逐级通过目录描述符打开，拒绝 symlink，避免路径检查与写入之间的竞态。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for component in parts[:-1]:
            if create:
                try:
                    os.mkdir(component, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def local_state(root, item, source=False):
    parts = checked_source(item['source']) if source else checked_path(item['path'])
    try:
        with parent_fd(root, parts) as fd:
            try:
                info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return 'MISSING'
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('目标不是普通文件（拒绝 symlink）')
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('目标不是普通文件')
                digest = hashlib.sha256()
                count = 0
                while True:
                    block = stream.read(65536)
                    if not block:
                        break
                    count += len(block)
                    digest.update(block)
            return 'OK' if count == item['bytes'] and digest.hexdigest() == item['sha256'] else 'MISMATCH'
    except FileNotFoundError:
        return 'MISSING'


class CheckedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@contextlib.contextmanager
def input_stream(root, item):
    if 'source' in item:
        with parent_fd(root, checked_source(item['source'])) as fd:
            source_fd = os.open(checked_source(item['source'])[-1],
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(source_fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('本地 metadata 必须为普通文件')
                yield stream
        return
    checked_url(item['url'])
    # 不继承代理配置、Cookie 或认证处理器；重定向同样逐次校验。
    opener = build_opener(ProxyHandler({}), CheckedRedirect())
    request = Request(item['url'], headers={'User-Agent': 'ai-infra-evolution-source-restore/1'})
    with opener.open(request, timeout=30) as response:
        checked_url(response.geturl())
        if response.status != 200:
            raise ValueError('上游响应不是 HTTP 200')
        yield response


def download(root, item):
    parts = checked_path(item['path'])
    with parent_fd(root, parts, create=True) as fd:
        name = '.restore-' + secrets.token_hex(16) + '.tmp'
        tmp_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(tmp_fd, 'wb') as output:
                with input_stream(root, item) as response:
                    digest = hashlib.sha256()
                    count = 0
                    while True:
                        block = response.read(min(65536, item['bytes'] - count + 1))
                        if not block:
                            break
                        count += len(block)
                        if count > item['bytes']:
                            raise ValueError('下载字节数超过固定值')
                        digest.update(block)
                        output.write(block)
                    if count != item['bytes'] or digest.hexdigest() != item['sha256']:
                        raise ValueError('下载 bytes/SHA-256 不匹配')
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o644)
            try:
                info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('拒绝替换 symlink 或非普通文件')
            except FileNotFoundError:
                pass
            os.replace(name, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--download', action='store_true', help='显式下载上游文件并复制本地 metadata')
    mode.add_argument('--verify', action='store_true', help='离线验证全部目标；缺失或不匹配返回 1')
    args = parser.parse_args(argv)
    root = Path(__file__).absolute().parent.parent
    if Path(__file__).is_symlink() or root.is_symlink() or (root / 'tools').is_symlink():
        parser.exit(2, 'ERROR: 拒绝通过 symlink 定位仓库\n')
    try:
        items = load_manifest(root / 'tools/upstream-sources.json')
        for item in items:
            if 'source' in item and local_state(root, item, source=True) != 'OK':
                raise ValueError('本地 metadata 来源缺失或 bytes/SHA-256 不匹配')
        # 所有目标先检查，再允许任何下载，避免遇到后续危险路径前部分写入。
        states = [(item, local_state(root, item)) for item in items]
        failures = 0
        for item, state in states:
            if args.download and state != 'OK':
                download(root, item)
                state = local_state(root, item)
                if state != 'OK':
                    raise ValueError('下载后离线校验失败')
            print(f'{state} {item["path"]}')
            failures += state != 'OK'
        label = 'DOWNLOAD' if args.download else 'VERIFY' if args.verify else 'DRY-RUN'
        for local, category in [(False, 'NETWORK'), (True, 'LOCAL-METADATA')]:
            subset = [item for item in items if ('source' in item) == local]
            valid = sum(local_state(root, item) == 'OK' for item in subset)
            print(f'{label}-{category}: total={len(subset)} ok={valid} missing_or_mismatch={len(subset)-valid}')
        return 1 if (args.verify or args.download) and failures else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # 不回显未经审查的 URL、认证信息或系统绝对路径。
        print(f'ERROR: 恢复已停止 ({type(exc).__name__})；请检查清单、目标路径和网络。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
