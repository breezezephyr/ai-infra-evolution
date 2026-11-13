"""Kaggle preparation only: no generation requests and no public server."""
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import subprocess
import sys
import time

RUN_ID = "exp29-kaggle-20261110-a74160a0"
OUT = Path("/kaggle/working") / RUN_ID
OUT.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = "/kaggle/temp/p5-exp29/hf"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
hardware = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,driver_version", "--format=csv"], capture_output=True, text=True, check=True).stdout
(OUT / "hardware-before.txt").write_text(hardware)
print(hardware, flush=True)
import torch
assert torch.cuda.is_available(), "No CUDA GPU; experiment must not fall back to CPU"
assert torch.cuda.mem_get_info(0)[0] >= 10 * 1024**3, "GPU0 has less than 10 GiB free"
print("Torch", torch.__version__, "CUDA", torch.version.cuda, flush=True)
deps = ["transformers==4.51.3", "tokenizers>=0.21,<0.22", "huggingface_hub>=0.30,<1.0", "safetensors>=0.5.3", "fastapi==0.115.12", "uvicorn==0.34.2", "httpx==0.28.1"]
with (OUT / "dependency-install.log").open("w") as log:
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *deps], stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((OUT / "dependency-install.log").read_text()[-7000:])
    raise RuntimeError("Dependency installation failed")
packages = {p: md.version(p) for p in ["torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "fastapi", "uvicorn", "httpx"]}
(OUT / "dependency-versions.json").write_text(json.dumps(packages, indent=2))
print("Dependencies", packages, flush=True)
from huggingface_hub import HfApi, snapshot_download
repo = "Qwen/Qwen3-4B"
revision = HfApi(token=False).model_info(repo).sha
print("Downloading", repo, "revision", revision, flush=True)
started = time.monotonic()
model_path = snapshot_download(repo, revision=revision, token=False, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"], max_workers=4)
manifest = []
for file in sorted(Path(model_path).rglob("*")):
    if file.is_file():
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(chunk)
        manifest.append({"path": str(file.relative_to(model_path)), "bytes": file.stat().st_size, "sha256": digest.hexdigest()})
prepared = {"run_id": RUN_ID, "repo": repo, "revision": revision, "model_path": model_path, "download_and_hash_seconds": time.monotonic()-started, "packages": packages, "files": manifest, "planned_http_requests": 5, "planned_max_generations": 3, "planned_output_token_cap_total": 65}
(OUT / "model-prepared.json").write_text(json.dumps(prepared, indent=2))
print("PREPARED", json.dumps({k:v for k,v in prepared.items() if k != "files"}), flush=True)
