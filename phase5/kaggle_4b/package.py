"""Package only reviewed code/docs/tests; never glob OUT, bootstrap, secrets or results."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

BASE = Path(__file__).resolve().parent


def main():
    files = [BASE / n for n in ['common.py', 'run_suite.py', 'check_cpu.py', 'package.py',
                               'README.md', 'source-provenance.json']]
    files += sorted((BASE / 'runtime').rglob('*.py'))
    files += sorted((BASE / 'tests').glob('*.py'))
    dest = BASE / 'dist'
    dest.mkdir(exist_ok=True)
    archive = dest / 'kaggle_4b.tar.gz'
    if archive.exists():
        raise FileExistsError('archive exists; preserve it or choose a new filename')
    manifest = {}
    with tarfile.open(archive, 'x:gz') as tar:
        for path in files:
            if path.is_symlink():
                raise ValueError('symlinks are not packaged')
            data = path.read_bytes()
            name = 'kaggle_4b/' + str(path.relative_to(BASE))
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
            manifest[name] = hashlib.sha256(data).hexdigest()
        data = (json.dumps(manifest, indent=2) + '\n').encode()
        info = tarfile.TarInfo('kaggle_4b/package-manifest.json')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dest / 'kaggle_4b.tar.gz.sha256').write_text(sha + '  kaggle_4b.tar.gz\n')
    print(str(archive))
    print(sha)


if __name__ == '__main__':
    main()
