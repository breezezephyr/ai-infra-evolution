"""Repeat local checks; all writes stay beside this file. No network calls."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
PHASE5 = HERE.parents[1]
EVIDENCE = HERE / "evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, arguments, cwd=HERE):
    command = [str(value) for value in arguments]
    result = subprocess.run(command, cwd=cwd, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
    (EVIDENCE / f"{name}.stdout.txt").write_bytes(result.stdout)
    (EVIDENCE / f"{name}.stderr.txt").write_bytes(result.stderr)
    record = {"name": name, "argv": command, "cwd": str(cwd),
              "returncode": result.returncode,
              "stdout": f"evidence/{name}.stdout.txt", "stderr": f"evidence/{name}.stderr.txt"}
    if name.endswith("tests"):
        suite = ET.parse(EVIDENCE / f"{name}.xml").getroot().find("testsuite")
        record["junit"] = {key: int(suite.attrib[key]) for key in ("tests", "errors", "failures", "skipped")}
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed; see saved stdout/stderr")
    return record


def main():
    EVIDENCE.mkdir(exist_ok=True)
    steps = [run("prepare", [sys.executable, "-B", HERE / "prepare_patch.py"])]
    patched = HERE / "patched-upstream"
    patch = HERE / "patch.diff"
    steps.append(run("patch-check", ["git", "apply", "--check", "--whitespace=error", patch], patched))
    steps.append(run("patch-apply", ["git", "apply", patch], patched))
    steps.append(run("patch-whitespace", ["git", "apply", "--check", "--whitespace=error", "--reverse", patch], patched))
    steps.append(run("repro", [sys.executable, "-B", HERE / "repro.py"]))
    repro = json.loads((EVIDENCE / "repro.stdout.txt").read_text())
    (EVIDENCE / "repro.stdout.json").write_text(json.dumps(repro, ensure_ascii=False, indent=2) + "\n")
    assert [(r["outcome"], r.get("value"), r.get("status_code")) for r in repro["rows"]] == [
        ("ConversionError", None, 400), ("returned", 1, None), ("returned", 1, None),
        ("ConversionError", None, 400), ("ConversionError", None, 400), ("returned", 1, None),
    ]
    for name, file, selection in (
        ("local-tests", HERE / "test_context_budget.py", None),
        ("upstream-baseline-tests", EVIDENCE / "upstream-current/deepseek-recipe-python/tests/test_bindings.py", "test_resolve_max_tokens"),
        ("upstream-patched-tests", patched / "deepseek-recipe-python/tests/test_bindings.py", "test_resolve_max_tokens"),
    ):
        args = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", file,
                f"--junitxml={EVIDENCE / (name + '.xml')}"]
        if selection:
            args.extend(["-k", selection])
        steps.append(run(name, args))
    assert [step["junit"]["tests"] for step in steps if "junit" in step] == [6, 1, 7]
    import deepseek_recipe
    package = Path(deepseek_recipe.__file__).parent
    native = next(package.glob("*.so"))
    wheel = PHASE5 / "vendor/deepseek_recipe-0.2.0-cp310-abi3-macosx_11_0_arm64.whl"
    with zipfile.ZipFile(wheel) as archive:
        native_member = next(name for name in archive.namelist() if name.endswith("/" + native.name))
        native_from_wheel_sha = hashlib.sha256(archive.read(native_member)).hexdigest()
    assert native_from_wheel_sha == sha(native)
    assert sha(package / "_native.pyi") == sha(EVIDENCE / "upstream-current/deepseek-recipe-python/python/deepseek_recipe/_native.pyi")
    historical = PHASE5 / "results/exp19/formal-v2/records.json"
    records = json.loads(historical.read_text())["records"]
    extracted = [{key: row[key] for key in ("id", "protocol", "input", "encoding", "context_probes", "checks")}
                 for row in records if row["family"] == "text_default"]
    (EVIDENCE / "historical-counterexample.json").write_text(json.dumps({
        "source_path": str(historical), "source_sha256": sha(historical), "records": extracted,
    }, ensure_ascii=False, indent=2) + "\n")
    workspace = PHASE5.parent
    protected = json.loads((EVIDENCE / "protected-baseline.json").read_text())
    changed = [row["path"] for row in protected if sha(workspace / row["path"]) != row["sha256"]]
    assert not changed, changed
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(), "status": "pass",
        "steps": steps, "environment": {
            "executable": sys.executable, "python": sys.version, "platform": platform.platform(),
            "recipe_version": importlib.metadata.version("deepseek-recipe"),
            "pytest_version": importlib.metadata.version("pytest"),
            "wheel": str(wheel), "wheel_sha256": sha(wheel),
            "installed_native": str(native), "native_sha256": sha(native),
            "wheel_native_matches": True, "stub_matches_fixed_current_source": True,
            "native_build_commit": None,
        },
        "protected_files_checked": len(protected), "protected_files_changed": changed,
        "evidence_scope": {
            "native_executed": True, "original_current_upstream_tests_selected": 1,
            "proposed_boundary_cases": 6, "patched_selected_cases": 7,
            "full_upstream_suite_run": False, "current_source_built": False,
            "synthetic_context_limits": True, "repro_prompt_tokens_actually_encoded": True,
            "model_calls": 0, "backend_dispatched": False, "remote_resources_started": False,
            "upstream_write_requests": 0,
        },
    }
    (EVIDENCE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary_path = HERE / "evidence.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        summary["last_verified_at_utc"] = result["checked_at_utc"]
        summary["environment"] = result["environment"]
        summary["checks"] = {step["name"]: {"returncode": step["returncode"],
            **({"junit": step["junit"]} if "junit" in step else {})} for step in steps}
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    manifest = {"generated_at_utc": result["checked_at_utc"],
                "scope": "all contribution files except manifest.json itself",
                "files": [{"path": str(path.relative_to(HERE)), "bytes": path.stat().st_size,
                           "sha256": sha(path)} for path in sorted(HERE.rglob("*"))
                          if path.is_file() and path != HERE / "manifest.json"]}
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "pass", "tests": {step["name"]: step["junit"] for step in steps if "junit" in step},
                      "prompt_tokens": len(repro["token_ids"]), "protected_files_changed": changed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
