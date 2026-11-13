"""Build a self-contained, private Kaggle notebook from reviewed local sources."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CTX = json.loads((ROOT / "active-run.json").read_text())
RUN = CTX["run_id"]
OUT = CTX["remote_output"]
CODE = "/kaggle/working/exp29-code"

def cell(kind, source):
    result = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result

bootstrap = (ROOT / "bootstrap.py").read_text()
preparation = "from pathlib import Path\n"
preparation += f"if Path({OUT + '/model-prepared.json'!r}).exists():\n    print('Preparation already exists; no generation here.')\nelse:\n"
preparation += "".join("    " + line + "\n" for line in bootstrap.splitlines())

setup = f'''from pathlib import Path
import json, subprocess, sys, hashlib, shutil
OUT = Path({OUT!r})
CODE = Path({CODE!r})
CODE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "notebook-context.json").write_text({json.dumps(CTX, ensure_ascii=False, indent=2)!r})
'''

execute = f'''from pathlib import Path
import subprocess, sys, json, hashlib, shutil
from IPython.display import FileLink, display
OUT = Path({OUT!r})
CODE = Path({CODE!r})
source_dir = OUT / "source"
source_dir.mkdir(exist_ok=True)
for name in ("experiment.py", "test_sse.py"):
    shutil.copy2(CODE / name, source_dir / name)
tests = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(CODE), "-p", "test_sse.py", "-v"], capture_output=True, text=True)
(OUT / "cpu-sse-tests.log").write_text(tests.stdout + tests.stderr)
print(tests.stdout + tests.stderr, flush=True)
assert tests.returncode == 0, "CPU SSE tests failed; no generation dispatched"
if (OUT / "experiment.started.json").exists():
    print("Existing experiment marker: readback only; no repeat generation.", flush=True)
else:
    with (OUT / "experiment-process.log").open("w") as log:
        proc = subprocess.run([sys.executable, str(CODE / "experiment.py"), "--out-dir", str(OUT), "--run-id", {RUN!r}, "--served-model", "qwen3-4b"], stdout=log, stderr=subprocess.STDOUT)
    print((OUT / "experiment-process.log").read_text()[-9000:], flush=True)
if (OUT / "summary.json").exists():
    print("RESULT", (OUT / "summary.json").read_text(), flush=True)
manifest = []
for path in sorted(OUT.rglob("*")):
    if path.is_file() and path.name != "artifact-manifest.json":
        manifest.append({{"path": str(path.relative_to(OUT)), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}})
(OUT / "artifact-manifest.json").write_text(json.dumps(manifest, indent=2))
bundle = shutil.make_archive(str(OUT), "zip", root_dir=OUT.parent, base_dir=OUT.name)
print("BUNDLE", bundle, "SHA256", hashlib.sha256(Path(bundle).read_bytes()).hexdigest(), flush=True)
display(FileLink(bundle))
'''

cells = [
    cell("markdown", "# P5 Infra - Qwen3 GPU Evidence\n\nIndependent Qwen/Qwen3-4B FP16 text experiment, 2026-11-10.\n\n5 serial loopback HTTP cases, no retries, at most 3 generations and 65 output-token reservations. Transformers eager backend, GPU0 only. Protocol evidence only; no quality, capacity, billing, or continuous-batching claim.\n\nThe original image notebook and prior failed experiment remain separate. No public server or tunnel.\n"),
    cell("code", preparation),
    cell("code", setup),
    cell("code", f"%%writefile {CODE}/experiment.py\n" + (ROOT / "experiment.py").read_text()),
    cell("code", f"%%writefile {CODE}/test_sse.py\n" + (ROOT / "test_sse.py").read_text()),
    cell("code", execute),
]
notebook = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
path = ROOT / "p5-qwen3-4b-exp29.ipynb"
path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n")
print(json.dumps({"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
