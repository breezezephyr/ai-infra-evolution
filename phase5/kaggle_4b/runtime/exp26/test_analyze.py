from common import canonical
"""Offline, independently authored raw fixtures and destructive audit mutations.

RED: python3 -B -m unittest discover -s phase5/exp26 -p test_analyze.py -v
Initial run: expected assertion 'independent analyzer has not been implemented'.
No gateway imports, network calls, or production fixture builders.
"""
import copy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

D = Path(__file__).resolve().parent
USAGE = {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
SYNTHETIC = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
CASES = [
    ("unconnected-retry", "completed", 2), ("pre-timeout-retry", "completed", 2),
    ("post-break", "backend_error", 1), ("review-reject", "review_rejected", 1),
    ("review-unavailable", "review_unavailable", 1), ("cancel-late", "cancelled", 1),
    ("stale-generation", "superseded", 1), ("drain-graceful", "completed", 1),
    ("drain-timeout", "drain_timeout", 1), ("drain-reject", "draining", 0),
    ("no-key", "backend_error", 1), ("duplicate-settlement", "completed", 1),
    ("gpu-normal", "completed", 1), ("gpu-pre-retry", "completed", 2),
    ("gpu-post-break", "backend_error", 1), ("gpu-disconnect", "client_disconnected", 1),
    ("gpu-drain-timeout", "drain_timeout", 1),
]


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def wire(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def fixture(out):
    """19 attempts: 13 controlled, 6 GPU. GPU known=18; controlled known=28."""
    plan = {"schema": 1, "experiment": "exp26", "backend_port": 8026,
            "gateway_port": 8126, "cases": [], "source_sha256": {}}
    shards=[dict(path='model-00001-of-00003.safetensors',bytes=1,sha256='a'*64),dict(path='model-00002-of-00003.safetensors',bytes=1,sha256='b'*64),dict(path='model-00003-of-00003.safetensors',bytes=1,sha256='c'*64)]
    manifest=dict(schema=1,algorithm='sha256-canonical-shard-manifest-v1',shards=shards,sha256=hashlib.sha256(canonical(shards)).hexdigest())
    plan['model_identity']=dict(weight_manifest=manifest,weights_sha256=manifest['sha256'],files={r['path']:r['sha256'] for r in shards})
    gateway, clients, backend, health = [], [], [], []
    for name, terminal, count in CASES:
        rid, mode = "exp26-" + name, "gpu" if name.startswith("gpu-") else "controlled"
        faults = {"unconnected-retry": ["unconnected", None],
                  "pre-timeout-retry": ["pre_timeout", None], "gpu-pre-retry": ["pre_timeout", None],
                  "post-break": ["post_break"], "gpu-post-break": ["post_break"],
                  "no-key": ["unconnected"]}.get(name, [])
        case = dict(case_id=name, request_id=rid, generation_id="g0", mode=mode,
                    terminal=terminal, attempts=count, faults=faults, control=None,
                    idempotency_key=None if name == "no-key" else "safe-text-" + name)
        if name in ("cancel-late", "stale-generation"):
            case.update(control="cancel" if name == "cancel-late" else "supersede", late=True)
        if "drain-timeout" in name:
            case["control"] = "drain_timeout"
        if name == "drain-graceful": case["control"] = "drain_graceful"
        if name == "drain-reject": case["pre_draining"] = True
        if name.startswith("review-"): case["review"] = "reject" if name.endswith("reject") else "unavailable"
        if name == "gpu-disconnect": case["client_disconnect"] = True
        if name == "duplicate-settlement": case["duplicate_settlement"] = True
        plan["cases"].append(case)
        row = dict(case_id=name, request_id=rid, generation_id="g0", mode=mode,
                   idempotency_key=case["idempotency_key"], started_ns=1, ended_ns=999,
                   clock_domain="gateway-123", committed=False, terminal=terminal,
                   attempts=[], settlements=[], events=[], sent_content="")
        tick = 2
        def event(event_name, **kw):
            nonlocal tick
            tick += 1
            row["events"].append(dict(event=event_name, ns=tick, **kw))
        packets = []
        for index in range(count):
            aid = rid + "/a" + str(index + 1)
            fault = (faults + [None, None])[index]
            success = terminal == "completed" and index == count - 1
            text = "OK" if success else ("O" if fault != "unconnected" and fault != "pre_timeout" else "")
            if name in ("review-reject", "review-unavailable"): text = "O"
            usage = (copy.deepcopy(USAGE if mode == "gpu" else SYNTHETIC) if success else None)
            outcome = "completed" if success else {"unconnected": "connect_refused", "pre_timeout": "first_content_timeout", "post_break": "injected_stream_break"}.get(fault, terminal)
            attempt = dict(request_id=rid, attempt_id=aid, mode=mode, target=f"logical-{index+1}-same-backend",
                           injected_fault=fault, started_ns=tick, usage=usage,
                           usage_source=("native_stream_usage" if mode == "gpu" else "synthetic_fixture") if usage else "unknown",
                           generated_content=text, finish="stop" if success else None,
                           worker_joined=True, outcome=outcome, raw_sse="")
            row["attempts"].append(attempt)
            event("attempt_started", attempt_id=aid)
            native = ""
            for char in text:
                native += wire({"choices": [{"delta": {"content": char}, "finish_reason": None}]})
                event("generated", attempt_id=aid, text=char)
                if not name.startswith("review-"):
                    event("content_send_started", attempt_id=aid)
                    packets.append(dict(id=rid, generation_id="g0", attempt_id=aid, type="content", content=char))
                    row["sent_content"] += char
                    event("content_sent", attempt_id=aid, text=char, after_stop=False)
            if terminal in ("cancelled", "superseded", "drain_timeout", "client_disconnected"):
                event("stop_requested", reason=terminal)
                if name in ("cancel-late", "stale-generation"):
                    attempt["generated_content"] += "迟到"
                    event("generated", attempt_id=aid, text="迟到")
                    event("late_discard", attempt_id=aid, kind="content")
            if success:
                native += wire({"choices": [{"delta": {}, "finish_reason": "stop"}]})
                native += wire({"choices": [], "usage": usage}) + "data: [DONE]\n\n"
            if mode == "gpu":
                body = {"model": "exp26-qwen3-4b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
                bodyraw = json.dumps(body, sort_keys=True, separators=(",", ":"))
                attempt.update(raw_sse=native, http_status=200, backend_body=body, backend_body_sha256=sha(bodyraw))
                backend.append(dict(component="backend-http", request_id=rid, attempt_id=aid,
                                    status=200, body=bodyraw, request_sha256=sha(bodyraw), sse=native,
                                    response_sha256=sha(native), started_ns=1, ended_ns=10,
                                    clock_domain="backend-987", error=None))
            event("worker_exited", attempt_id=aid)
            attempt["ended_ns"] = tick
            row["settlements"].append(dict(attempt_id=aid, usage=usage, source=attempt["usage_source"]))
            if name == "duplicate-settlement": event("settlement_replayed", attempt_id=aid, inserted=False)
            event("attempt_joined", attempt_id=aid)
            if index < count - 1: event("retry_allowed", from_attempt=aid)
        if count:
            event("request_finished", terminal=terminal)
            row["sent_sha256"] = sha(row["sent_content"])
        else:
            event("rejected_draining")
        row["committed"] = bool(row["sent_content"])
        if terminal != "client_disconnected" and count:
            packets.append(dict(id=rid, type="terminal", terminal=terminal, generation_id="g0",
                                attempt_ids=[a["attempt_id"] for a in row["attempts"]],
                                settlements=copy.deepcopy(row["settlements"]), finish="stop" if terminal == "completed" else None))
        raw = "".join(wire(p) for p in packets)
        if count and terminal != "client_disconnected": raw += "data: [DONE]\n\n"
        if not count: raw = json.dumps({"request_id": rid, "error": "draining"})
        clients.append(dict(case_id=name, request_id=rid, status=200 if count else 503, raw=raw,
                            clock_domain="client-321", started_ns=1, ended_ns=100,
                            client_closed_intentionally=terminal == "client_disconnected"))
        gateway.append(row)
        health.append(dict(case_id=name, state={"active": 0, "workers": 0}, ns=1000))
    (out / "code").mkdir()
    for filename in ("gateway.py", "serve_gateway.py", "run.py", "analyze.py", "backend_audit.py"):
        (out / "code" / filename).write_text("# frozen fixture: " + filename)
        plan["source_sha256"][filename] = sha((out / "code" / filename).read_bytes())
    def dump(name, value): (out / name).write_text(json.dumps(value, ensure_ascii=False))
    dump("plan.json", plan)
    for name, rows in (("gateway.jsonl", gateway), ("backend.jsonl", backend)):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    dump("clients.json", clients); dump("health.json", health)
    freeze = dict(plan_sha256=sha((out / "plan.json").read_bytes()), source_sha256=plan["source_sha256"], frozen_ns=1)
    dump("freeze.json", freeze)
    dump("gateway-startup.json", {**freeze, "pid": 123, "port": 8126, "clock_domain": "gateway-123"})


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((D / "analyze.py").exists(), "independent analyzer has not been implemented")
        spec = importlib.util.spec_from_file_location("exp26_independent_analyzer", D / "analyze.py")
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name); fixture(self.out)

    def read(self, name):
        text = (self.out / name).read_text()
        return [json.loads(line) for line in text.splitlines()] if name.endswith("jsonl") else json.loads(text)

    def write(self, name, value):
        (self.out / name).write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in value) if name.endswith("jsonl") else json.dumps(value, ensure_ascii=False))

    def rejected(self):
        r = self.module.analyze(self.out,evidence_profile="http_fixture")
        self.assertFalse(r["accepted"], r)
        self.assertIsNone(r["metrics"])
        self.assertTrue(r["errors"])
        self.assertEqual(r["planned"], 17)
        return r

    def test_accepts_17_cases_with_separate_usage_and_unknown_failure_costs(self):
        r = self.module.analyze(self.out,evidence_profile="http_fixture")
        self.assertTrue(r["accepted"], r["errors"])
        self.assertEqual(r["metrics"]["gpu"]["known_total_tokens"], 18)
        self.assertEqual(r["metrics"]["controlled"]["known_total_tokens"], 28)
        self.assertEqual(r["metrics"]["gpu"]["unknown_usage_attempts"], 4)
        self.assertEqual(len(r["attempt_ledger"]), 19)
        self.assertEqual(json.loads((self.out / "summary.json").read_text()), r)
        self.assertEqual(r["backend"]["engine_abort_evidence"], "unknown")

    def test_deleted_attempt_cannot_erase_failed_cost(self):
        g = self.read("gateway.jsonl"); del g[0]["attempts"][0]; self.write("gateway.jsonl", g); self.rejected()

    def test_duplicate_settlement_is_rejected_even_if_identical(self):
        g = self.read("gateway.jsonl"); g[0]["settlements"].append(copy.deepcopy(g[0]["settlements"][0])); self.write("gateway.jsonl", g); self.rejected()

    def test_each_client_metadata_field_is_checked_per_packet(self):
        original = self.read("clients.json")
        for field, value in (("id", "wrong"), ("generation_id", "g9"), ("attempt_id", "wrong"), ("content", "forged")):
            with self.subTest(field=field):
                c = copy.deepcopy(original); packet, tail = c[0]["raw"].split("\n\n", 1)
                p = json.loads(packet[6:]); p[field] = value; c[0]["raw"] = wire(p) + tail
                self.write("clients.json", c); self.rejected()

    def test_duplicate_request_id_cannot_be_hidden_by_dictionary_join(self):
        g = self.read("gateway.jsonl"); g[1]["request_id"] = g[0]["request_id"]; self.write("gateway.jsonl", g); self.rejected()

    def test_duplicate_attempt_id_is_rejected(self):
        g = self.read("gateway.jsonl"); g[1]["attempts"][0]["attempt_id"] = g[0]["attempts"][0]["attempt_id"]; self.write("gateway.jsonl", g); self.rejected()

    def test_post_break_cannot_splice_content_from_another_attempt(self):
        g = self.read("gateway.jsonl"); g[2]["events"].insert(-1, dict(event="content_sent", ns=997, attempt_id=g[0]["attempts"][1]["attempt_id"], text="K", after_stop=False)); self.write("gateway.jsonl", g); self.rejected()

    def test_retry_must_follow_join_and_precede_any_commit(self):
        original = self.read("gateway.jsonl")
        for mutation in ("join", "commit", "key"):
            with self.subTest(mutation=mutation):
                g = copy.deepcopy(original); r = g[0]
                if mutation == "join": r["attempts"][0]["worker_joined"] = False
                if mutation == "key": r["idempotency_key"] = ""
                if mutation == "commit":
                    pos = next(i for i, e in enumerate(r["events"]) if e["event"] == "retry_allowed")
                    r["events"].insert(pos, dict(event="content_sent", attempt_id=r["attempts"][0]["attempt_id"], text="X", ns=r["events"][pos]["ns"]))
                self.write("gateway.jsonl", g); self.rejected()

    def test_send_started_after_stop_is_rejected_even_with_after_stop_false(self):
        g = self.read("gateway.jsonl"); r = g[5]
        pos = next(i for i, e in enumerate(r["events"]) if e["event"] == "content_send_started")
        r["events"].insert(pos, dict(event="stop_requested", reason="cancelled", ns=r["events"][pos]["ns"]))
        r["events"] = [e for i, e in enumerate(r["events"]) if not (e["event"] == "stop_requested" and i > pos)]
        self.write("gateway.jsonl", g); self.rejected()

    def test_inflight_send_can_commit_after_stop_if_started_before_stop(self):
        g = self.read("gateway.jsonl"); r = g[5]
        stop = next(e for e in r["events"] if e["event"] == "stop_requested")
        r["events"].remove(stop)
        pos = next(i for i, e in enumerate(r["events"]) if e["event"] == "content_sent")
        stop["ns"] = r["events"][pos]["ns"]; r["events"].insert(pos, stop)
        self.write("gateway.jsonl", g)
        self.assertTrue(self.module.analyze(self.out,evidence_profile="http_fixture")["accepted"])

    def test_terminal_done_attempt_list_and_settlement_payload_are_checked(self):
        original = self.read("clients.json")
        for mutation in ("done", "terminal", "attempt_ids", "settlements", "finish", "after_done"):
            with self.subTest(mutation=mutation):
                c = copy.deepcopy(original)
                if mutation == "done": c[0]["raw"] = c[0]["raw"].replace("data: [DONE]\n\n", "")
                else:
                    parts = c[0]["raw"].split("\n\n"); p = json.loads(parts[-3][6:])
                    if mutation == "terminal": c[0]["raw"] = wire(p) + c[0]["raw"]
                    elif mutation == "after_done": c[0]["raw"] += wire(p)
                    else:
                        p[mutation] = [] if mutation in ("attempt_ids", "settlements") else "length"
                        parts[-3] = wire(p).rstrip("\n"); c[0]["raw"] = "\n\n".join(parts)
                self.write("clients.json", c); self.rejected()

    def test_gpu_disconnect_can_observe_packet_prefix_without_terminal(self):
        c = self.read("clients.json"); c[15]["raw"] = ""; self.write("clients.json", c)
        self.assertTrue(self.module.analyze(self.out,evidence_profile="http_fixture")["accepted"])

    def test_native_full_partial_usage_and_unicode_multiline_sse(self):
        raw = wire({"choices": [{"delta": {"content": "你好"}, "finish_reason": "stop"}]}) + wire({"choices": [], "usage": USAGE})
        p = self.module.parse_native_sse(raw + "data: [DONE]\n\n")
        self.assertTrue(p["complete"]); self.assertEqual(p["usage"], USAGE); self.assertEqual(p["content"], "你好")
        p = self.module.parse_native_sse(raw + 'data: {"choices":')
        self.assertFalse(p["complete"]); self.assertEqual(p["usage"], USAGE)
        multiline = 'data: {"choices": [],\r\ndata: "usage": ' + json.dumps(USAGE) + '}\r\n\r\n'
        self.assertEqual(self.module.parse_native_sse(multiline)["usage"], USAGE)

    def test_native_usage_cannot_be_erased_from_failed_attempt(self):
        g = self.read("gateway.jsonl"); a = g[14]["attempts"][0]
        a["raw_sse"] += wire({"choices": [], "usage": USAGE}); self.write("gateway.jsonl", g)
        r = self.rejected(); self.assertEqual(next(x for x in r["attempt_ledger"] if x["attempt_id"] == a["attempt_id"])["native_usage"], USAGE)

    def test_known_failure_usage_is_settled_and_included_in_gpu_totals(self):
        g = self.read("gateway.jsonl"); a = g[14]["attempts"][0]
        a.update(usage=USAGE, usage_source="native_stream_usage"); a["raw_sse"] += wire({"choices": [], "usage": USAGE})
        g[14]["settlements"][0].update(usage=USAGE, source="native_stream_usage"); self.write("gateway.jsonl", g)
        c = self.read("clients.json"); c[14]["raw"] = c[14]["raw"].replace('"usage":null,"source":"unknown"', '"usage":' + json.dumps(USAGE, separators=(",", ":")) + ',"source":"native_stream_usage"'); self.write("clients.json", c)
        b = self.read("backend.jsonl"); row = next(x for x in b if x["attempt_id"] == a["attempt_id"]); row.update(sse=a["raw_sse"], response_sha256=sha(a["raw_sse"])); self.write("backend.jsonl", b)
        r = self.module.analyze(self.out,evidence_profile="http_fixture"); self.assertTrue(r["accepted"], r["errors"])
        self.assertEqual(r["metrics"]["gpu"]["known_total_tokens"], 27)

    def test_http_evidence_is_required_and_corruption_or_missing_join_is_rejected(self):
        original = self.read("backend.jsonl")
        self.write("backend.jsonl", []); self.rejected()
        for mutation in ("missing", "hash", "duplicate", "request_id", "body"):
            with self.subTest(mutation=mutation):
                b = copy.deepcopy(original)
                if mutation == "missing": b.pop()
                if mutation == "hash": b[0]["response_sha256"] = "wrong"
                if mutation == "duplicate": b.append(copy.deepcopy(b[0]))
                if mutation == "request_id": b[0]["request_id"] = "wrong"
                if mutation == "body": b[0]["body"] = '{}'
                self.write("backend.jsonl", b); self.rejected()

    def test_health_startup_freeze_source_and_malformed_input_fail_closed(self):
        for name, mutation in (("health.json", "workers"), ("gateway-startup.json", "plan"), ("freeze.json", "plan"), ("clients.json", "malformed")):
            with self.subTest(name=name):
                saved = (self.out / name).read_bytes()
                if mutation == "workers":
                    value = self.read(name); value[0]["state"]["workers"] = 1; self.write(name, value)
                elif mutation == "plan":
                    value = self.read(name); value["plan_sha256"] = "wrong"; self.write(name, value)
                else: (self.out / name).write_text('{')
                self.rejected(); (self.out / name).write_bytes(saved)
        (self.out / "code/gateway.py").write_text("changed"); self.rejected()

    def test_cli_returns_nonzero_and_writes_rejected_summary(self):
        (self.out / "gateway.jsonl").write_text("")
        proc = subprocess.run([sys.executable, "-B", str(D / "analyze.py"), "--out", str(self.out)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.read("summary.json")["accepted"])

    def add_native_rows(self):
        rows = self.read("backend.jsonl")
        native = [dict(event="hooks_installed", installed=True, vllm_version="0.8.5",
                       hooks=["AsyncLLMEngine.add_request", "AsyncLLMEngine.abort", "AsyncLLMEngine._abort",
                              "RequestTracker.abort_request", "RequestTracker.process_request_output",
                              "LLMEngine.abort_request", "LLMEngine.step", "_AsyncLLMEngine.step_async", "AsyncLLMEngine.engine_step"], audit_errors=0)]
        for row in rows:
            aid = row["attempt_id"]; eid = "engine-" + aid; hid = "http-" + aid
            identity = dict(attempt_id=aid, request_id=row["request_id"], http_id=hid)
            row.update(identity, event="http_finished", engine_request_ids=[eid], audit_errors=0,
                       request_b64=base64.b64encode(row["body"].encode()).decode(),
                       response_b64=base64.b64encode(row["sse"].encode()).decode(),
                       send_returned_b64=base64.b64encode(row["sse"].encode()).decode(),
                       request_complete=True, response_complete=True, disconnect_observed=False)
            native.append(dict(identity, event="http_started", method="POST", path="/v1/chat/completions"))
            native.append(dict(identity, event="engine_request", engine_request_id=eid))
            normal = aid in ("exp26-gpu-normal/a1", "exp26-gpu-pre-retry/a2")
            if normal:
                native.append(dict(identity, event="engine_finished", engine_request_id=eid, finished=True, outputs=[]))
            else:
                native.append(dict(identity, event="abort_called", engine_request_id=eid, hook="LLMEngine.abort_request"))
                native.append(dict(identity, event="abort_returned", engine_request_id=eid, hook="LLMEngine.abort_request", error=None))
            native.append(dict(identity, event="state_after", engine_request_id=eid, snapshot_complete=True,
                               scheduler_unfinished=False, engine_pending_or_unfinished=False,
                               pending_or_unfinished=False, queues=[], cached=[],
                               tracker={"active_stream": False, "new_pending": False, "abort_pending": False},
                               hook="AsyncLLMEngine.engine_step", engine_object_id=99, error=None))
            native.append(row)
        for i, row in enumerate(native):
            row.update(schema="exp26.backend.v1", pid=987, clock_domain="backend-987", backend_monotonic_ns=i+1, wall_time_ns=10000+i)
        self.write("backend.jsonl", native)
        return native

    def test_native_engine_hooks_bind_ids_abort_and_scheduler_separately(self):
        self.add_native_rows(); r = self.module.analyze(self.out,evidence_profile="http_fixture")
        self.assertTrue(r["accepted"], r["errors"])
        self.assertEqual(r["backend"]["engine_abort_evidence"], "checked_cpu_hooks")
        self.assertEqual(len(r["backend"]["engine_attempts"]), 6)
        aborted = next(x for x in r["backend"]["engine_attempts"] if x["attempt_id"] == "exp26-gpu-disconnect/a1")
        self.assertTrue(aborted["abort_called"])
        self.assertTrue(aborted["scheduler_quiescent"])
        self.assertEqual(aborted["gpu_kernel_stopped"], "unknown")

    def test_native_missing_binding_abort_or_dirty_scheduler_fails(self):
        original = self.add_native_rows()
        for mutation in ("binding", "abort", "scheduler", "false_clean", "clock", "audit_errors", "observation_error"):
            with self.subTest(mutation=mutation):
                rows = copy.deepcopy(original); aid = "exp26-gpu-disconnect/a1"
                if mutation == "binding": rows = [r for r in rows if not (r.get("attempt_id") == aid and r["event"] == "engine_request")]
                if mutation == "abort": rows = [r for r in rows if not (r.get("attempt_id") == aid and r["event"] in ("abort_called", "abort_returned"))]
                if mutation in ("scheduler", "false_clean"):
                    r = next(r for r in rows if r.get("attempt_id") == aid and r["event"] == "state_after")
                    if mutation == "scheduler": r["pending_or_unfinished"] = True
                    else: r["queues"] = [{"engine_request_id": r["engine_request_id"], "unfinished": True, "queue": "running"}]
                if mutation == "clock": rows[-2]["clock_domain"] = "unrelated-clock"
                if mutation == "audit_errors": rows[-1]["audit_errors"] = 1
                if mutation == "observation_error": rows[-2]["event"] = "observation_error"
                self.write("backend.jsonl", rows); self.rejected()

    def test_native_http_ids_and_base64_bytes_cannot_disagree(self):
        original = self.add_native_rows()
        for mutation in ("engine_id", "http_id", "b64"):
            with self.subTest(mutation=mutation):
                rows = copy.deepcopy(original); row = next(r for r in rows if r["event"] == "http_finished")
                if mutation == "engine_id": row["engine_request_ids"] = ["forged-engine"]
                if mutation == "http_id": row["http_id"] = "forged-http"
                if mutation == "b64": row["response_b64"] = "eA=="
                self.write("backend.jsonl", rows); self.rejected()

    def test_retry_reordered_after_new_attempt_is_rejected(self):
        g = self.read("gateway.jsonl"); events = g[0]["events"]
        joined = next(e for e in events if e["event"] == "attempt_joined")
        events.remove(joined); events.append(joined)
        for i, e in enumerate(events): e["ns"] = i + 3
        self.write("gateway.jsonl", g); self.rejected()

    def test_native_malformed_complete_frame_and_duplicate_usage_are_rejected(self):
        g = self.read("gateway.jsonl")
        g[12]["attempts"][0]["raw_sse"] += wire({"usage": USAGE, "choices": []})
        self.write("gateway.jsonl", g); self.rejected()
        parsed = self.module.parse_native_sse('data: {broken}\n\n')
        self.assertTrue(parsed["errors"])


if __name__ == "__main__":
    unittest.main()

class ReviewRegressions(unittest.TestCase):
    setUp=AnalyzerTests.setUp
    read=AnalyzerTests.read
    write=AnalyzerTests.write

    def test_formal_empty_backend_cannot_downgrade_to_optional(self):
        self.write('backend.jsonl', [])
        r=self.module.analyze(self.out)
        self.assertFalse(r['accepted']);self.assertIsNone(r['metrics'])

    def test_formal_http_only_evidence_cannot_replace_native_hooks(self):
        r=self.module.analyze(self.out)
        self.assertFalse(r['accepted']);self.assertIsNone(r['metrics'])

    def test_gpu_attempts_require_backend_even_if_body_fields_are_erased(self):
        rows=self.read('gateway.jsonl')
        for r in rows:
            for a in r['attempts']:
                if a['mode']=='gpu':
                    a.pop('backend_body',None);a.pop('backend_body_sha256',None)
        self.write('gateway.jsonl',rows);self.write('backend.jsonl',[])
        r=self.module.analyze(self.out)
        self.assertFalse(r['accepted']);self.assertIsNone(r['metrics'])

    def test_backend_known_usage_missing_at_gateway_is_retained_and_blocks_acceptance(self):
        rows=self.read('backend.jsonl');r=next(x for x in rows if x['attempt_id']=='exp26-gpu-post-break/a1')
        r['sse']+=wire({'choices':[{'delta':{},'finish_reason':'stop'}]})+wire({'choices':[],'usage':USAGE})+'data: [DONE]\n\n'
        r['response_sha256']=sha(r['sse']);self.write('backend.jsonl',rows)
        report=self.module.analyze(self.out,evidence_profile='http_fixture')
        self.assertFalse(report['accepted']);self.assertIsNone(report['metrics'])
        a=next(x for x in report['attempt_ledger'] if x['attempt_id']==r['attempt_id'])
        self.assertIsNone(a['usage']);self.assertEqual(a['backend_http_usage'],USAGE)
        self.assertEqual(a['resource_usage'],USAGE);self.assertEqual(a['resource_usage_source'],'backend_http')
