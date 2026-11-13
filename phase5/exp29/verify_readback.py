"""Verify downloaded raw artifacts without generating or contacting any service."""
import base64
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
read = lambda p: json.loads((root / p).read_text())
digest = lambda data: hashlib.sha256(data).hexdigest()
manifest = read("artifact-manifest.json")
for entry in manifest:
    path = root / entry["path"]
    assert path.is_relative_to(root), entry["path"]
    data = path.read_bytes()
    assert len(data) == entry["bytes"] and digest(data) == entry["sha256"], entry["path"]

summary, plan, budget, environment = (read(p) for p in ("summary.json", "plan.json", "budget.json", "environment.json"))
assert summary["technical_contract_pass"] and summary["passed_requests"] == 5
assert summary["cleanup"]["process_exited"] and summary["cleanup"]["exitcode"] == 0
assert budget["http_requests"] == 5 and budget["generate_calls"] == 3 and budget["completed_generations"] == 3
assert budget["reserved_output_tokens"] == 65 and budget["actual_output_tokens"] <= 65
assert environment["parameter_devices"] == ["cuda:0"] and environment["parameter_dtypes"] == ["torch.float16"]
assert environment["parameter_count"] > 3_000_000_000
assert digest((root / "source/experiment.py").read_bytes()) == "dacfc38bc8fc2d57970219e5d9a6be6811ba627b176faa1366b8ce3f3e68f0b7"
actual_tokens, rows = 0, []
for case in plan["cases"]:
    folder = root / "client" / case["case_id"]
    row = json.loads((folder / "result.json").read_text())
    assert row["state"] == "passed" and row["status"] == case["expected_status"]
    request = (folder / "request.body.bin").read_bytes()
    raw = (folder / "response.raw.bin").read_bytes()
    assert digest(request) == case["body_sha256"]
    assert digest(raw) == row["response_raw_sha256"]
    parts = [json.loads(line) for line in (folder / "reads.jsonl").read_text().splitlines()]
    assert b"".join(base64.b64decode(p["base64"]) for p in parts) == raw
    native = read("server/" + row["actual_server_request_id"] + ".json")
    assert native["body_sha256"] == digest(request)
    assert native["client_request_id"] == case["client_request_id"]
    if row["status"] == 200:
        count = len(native["output_token_ids"])
        assert count == row["http_usage"]["completion_tokens"]
        assert len(native["input_token_ids"]) == row["http_usage"]["prompt_tokens"]
        assert row["text"] == native["text"]
        actual_tokens += count
    else:
        assert native["native_state"] == "not_run" and "generate_started_ns" not in native
        count = 0
    if case["body"]["stream"]:
        assert row["done"] and raw.rstrip().endswith(b"data: [DONE]")
    rows.append({"case": case["case_id"], "status": row["status"], "generated_tokens": count,
                 "read_fragments": len(parts), "client_first_content_ms": (row["first_nonempty_content_rel_ns"] / 1e6 if row["first_nonempty_content_rel_ns"] is not None else None),
                 "client_total_ms": row["full_duration_ns"] / 1e6})
assert actual_tokens == budget["actual_output_tokens"]
result = {"artifact_hashes_verified": len(manifest), "all_five_cases_verified": True,
          "raw_http_reassembled": True, "actual_output_tokens": actual_tokens, "cases": rows,
          "scope": "local readback of one downloaded remote run; no new generation"}
print(json.dumps(result, ensure_ascii=False, indent=2))
