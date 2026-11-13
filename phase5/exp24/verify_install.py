"""Pin official wheel and compare installed native modules; no build-commit inference."""
import json,pathlib,urllib.request,hashlib,zipfile,importlib.metadata,platform,sys,subprocess
R=pathlib.Path(__file__).resolve().parent
x=json.loads((R/'wheel-identity-input.json').read_text());wheel=R/x['filename']
if not wheel.exists():urllib.request.urlretrieve(x['url'],wheel)
digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
assert digest==x['digests']['sha256']
import mooncake
root=pathlib.Path(mooncake.__file__).parent
checks=[]
with zipfile.ZipFile(wheel) as z:
    for name in z.namelist():
        if name.startswith('mooncake/') and (name.endswith('.so') or name.endswith('/mooncake_master')):
            installed=root.parent/name
            checks.append({'path':name,'wheel_sha256':hashlib.sha256(z.read(name)).hexdigest(),
                           'installed_sha256':hashlib.sha256(installed.read_bytes()).hexdigest()})
assert checks and all(x['wheel_sha256']==x['installed_sha256'] for x in checks)
report={'package':'mooncake-transfer-engine-non-cuda','version':importlib.metadata.version('mooncake-transfer-engine-non-cuda'),
    'wheel_sha256':digest,'wheel_url':x['url'],'filename':x['filename'],'native_file_checks':checks,
    'source_read_commit':'c67a88f381f69e869045f353539e90c76e738830','binary_build_commit_verified':False,
    'python':sys.version,'uname':platform.uname()._asdict(),
    'runtime_debs':[{'name':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(R.glob('*.deb'))]}
(R/'binary-identity.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'version':report['version'],'native_files_matched':len(checks),'wheel_sha256':digest}))
