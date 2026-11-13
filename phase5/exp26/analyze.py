"""Independent exp26 evidence audit, stdlib only; never imports the gateway.

API: analyze(out: str | Path) -> dict, writes out/summary.json. CLI: --out DIR.
Required: plan.json, gateway.jsonl, clients.json, backend.jsonl (may be empty),
health.json, freeze.json, gateway-startup.json and frozen code/* source files.
Client SSE is read from raw; gateway per-attempt native bytes from raw_sse.
Optional backend-http rows use request_id/attempt_id, body/request_sha256,
sse/response_sha256, status and an independent clock_domain. HTTP exit does
not establish engine abort. Unknown usage is retained as null, never zero.
Only accepted evidence produces metrics; the observed attempt ledger survives
failure, including failed/cancelled attempts and native usage discrepancies.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path


# Independent acceptance contract, deliberately not derived from make_plan().
EXPECTED = {
    "unconnected-retry": ("completed", 2, "controlled", ["unconnected", None]),
    "pre-timeout-retry": ("completed", 2, "controlled", ["pre_timeout", None]),
    "post-break": ("backend_error", 1, "controlled", ["post_break"]),
    "review-reject": ("review_rejected", 1, "controlled", []),
    "review-unavailable": ("review_unavailable", 1, "controlled", []),
    "cancel-late": ("cancelled", 1, "controlled", []),
    "stale-generation": ("superseded", 1, "controlled", []),
    "drain-graceful": ("completed", 1, "controlled", []),
    "drain-timeout": ("drain_timeout", 1, "controlled", []),
    "drain-reject": ("draining", 0, "controlled", []),
    "no-key": ("backend_error", 1, "controlled", ["unconnected"]),
    "duplicate-settlement": ("completed", 1, "controlled", []),
    "gpu-normal": ("completed", 1, "gpu", []),
    "gpu-pre-retry": ("completed", 2, "gpu", ["pre_timeout", None]),
    "gpu-post-break": ("backend_error", 1, "gpu", ["post_break"]),
    "gpu-disconnect": ("client_disconnected", 1, "gpu", []),
    "gpu-drain-timeout": ("drain_timeout", 1, "gpu", []),
}
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key: " + key)
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON: " + value)))


def _sse(raw):
    """Frame actual SSE boundaries; do not salvage an unfinished JSON packet."""
    errors, objects, order = [], [], []
    if not isinstance(raw, str):
        return dict(objects=[], order=[], done_count=0, tail="", errors=["SSE must be text"])
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    frames = raw.split("\n\n")
    tail = frames.pop()
    done = 0
    for frame in frames:
        data = []
        for line in frame.split("\n"):
            if line.startswith("data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(" ") else value)
        if not data:
            continue
        value = "\n".join(data)
        if done:
            errors.append("event after DONE")
        if value == "[DONE]":
            done += 1
            order.append("done")
            continue
        try:
            obj = _json(value)
            if not isinstance(obj, dict):
                raise ValueError("SSE data must be an object")
            objects.append(obj)
            order.append(obj)
        except (ValueError, TypeError) as exc:
            errors.append("malformed SSE: " + str(exc))
    return dict(objects=objects, order=order, done_count=done, tail=tail, errors=errors)


def _valid_usage(usage):
    return (isinstance(usage, dict)
            and all(type(usage.get(k)) is int and usage[k] >= 0 for k in TOKEN_FIELDS)
            and usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"])


def parse_native_sse(raw):
    """Parse full/partial OpenAI native SSE independently, preserving partial usage.

    Complete, delimited usage frames count even if the stream has no DONE.
    Incomplete tails never supply usage. Invalid complete packets remain errors.
    """
    parsed = _sse(raw)
    errors = list(parsed["errors"])
    usage, finish, content = None, None, ""
    for obj in parsed["objects"]:
        if obj.get("usage") is not None:
            if usage is not None:
                errors.append("duplicate usage frame")
            usage = obj["usage"]
            if not _valid_usage(usage):
                errors.append("invalid native token usage")
        choices = obj.get("choices", [])
        if not isinstance(choices, list):
            errors.append("native choices must be a list")
            continue
        if len(choices) > 1:
            errors.append("multiple native choices outside text-only contract")
        for choice in choices:
            if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                errors.append("invalid native choice/delta")
                continue
            text = choice.get("delta", {}).get("content")
            if text is not None and not isinstance(text, str):
                errors.append("native content must be text")
            elif text:
                if finish is not None:
                    errors.append("native content after finish")
                content += text
            if choice.get("finish_reason") is not None:
                if finish is not None:
                    errors.append("duplicate native finish")
                finish = choice["finish_reason"]
    complete = (parsed["done_count"] == 1 and not parsed["tail"].strip()
                and finish in ("stop", "length") and not errors)
    return dict(usage=usage, content=content, finish=finish, done_count=parsed["done_count"],
                complete=complete, partial=not complete, tail=parsed["tail"], errors=errors)


class _Audit:
    def __init__(self, out, summary_path=None, evidence_profile="formal_native"):
        if evidence_profile not in ("formal_native", "http_fixture"):
            raise ValueError("unknown evidence profile")
        self.evidence_profile = evidence_profile
        self.out, self.errors, self.ledger = Path(out), [], []
        self.summary_path = Path(summary_path) if summary_path is not None else self.out / "summary.json"
        self.attempt_ids = set()

    def check(self, condition, code, context, detail=""):
        if not condition:
            self.errors.append(dict(code=code, context=context, detail=str(detail)))
        return bool(condition)

    def load(self, name, rows=False):
        try:
            raw = (self.out / name).read_text(encoding="utf-8")
            value = [_json(line) for line in raw.splitlines() if line.strip()] if name.endswith("jsonl") else _json(raw)
            if rows and (not isinstance(value, list) or any(not isinstance(v, dict) for v in value)):
                raise ValueError("expected list of object rows")
            if not rows and not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except (OSError, ValueError, TypeError) as exc:
            self.check(False, "input", name, exc)
            return [] if rows else {}

    def unique(self, rows, key, context):
        result = {}
        for row in rows:
            value = row.get(key)
            if self.check(isinstance(value, str) and bool(value), "missing_id", context, key):
                self.check(value not in result, "duplicate_" + key, context, value)
                if value not in result:
                    result[value] = row
        return result

    def provenance(self, plan, gateway):
        freeze, startup = self.load("freeze.json"), self.load("gateway-startup.json")
        try:
            plan_hash = _sha((self.out / "plan.json").read_bytes())
        except OSError:
            plan_hash = None
        sources = plan.get("source_sha256", {})
        self.check(isinstance(sources, dict) and {"gateway.py", "serve_gateway.py", "run.py", "analyze.py", "backend_audit.py"} <= set(sources), "source_manifest", "plan")
        if not isinstance(sources, dict):
            sources = {}
        for obj, label in ((freeze, "freeze"), (startup, "gateway-startup")):
            self.check(obj.get("plan_sha256") == plan_hash and plan_hash is not None, "plan_hash", label)
            self.check(obj.get("source_sha256") == sources, "source_manifest", label)
        for name, digest in sources.items():
            if not self.check(isinstance(name, str) and Path(name).name == name and name.endswith(".py"), "source_path", str(name)):
                continue
            try:
                self.check(_sha((self.out / "code" / name).read_bytes()) == digest, "source_hash", name)
            except OSError as exc:
                self.check(False, "source_hash", name, exc)
        self.check(type(startup.get("pid")) is int and startup["pid"] > 0, "startup_pid", "gateway-startup")
        self.check(startup.get("port") == plan.get("gateway_port") == 8126, "startup_port", "gateway-startup")
        domain = startup.get("clock_domain")
        self.check(isinstance(domain, str) and bool(domain), "clock_domain", "gateway-startup")
        for row in gateway:
            self.check(row.get("clock_domain") == domain, "clock_domain", str(row.get("case_id")))

    def audit_plan(self, plan):
        self.check(plan.get("experiment") == "exp26" and plan.get("schema") == 1, "plan_schema", "plan")
        cases = plan.get("cases", [])
        if not isinstance(cases, list) or any(not isinstance(c, dict) for c in cases):
            self.check(False, "plan_cases", "plan")
            return {}
        indexed = self.unique(cases, "case_id", "plan")
        self.unique(cases, "request_id", "plan")
        self.check(set(indexed) == set(EXPECTED) and len(cases) == 17, "plan_denominator", "plan", "17 cases: controlled12 GPU5")
        for name, case in indexed.items():
            if name not in EXPECTED:
                continue
            terminal, count, mode, faults = EXPECTED[name]
            for field, expected in (("terminal", terminal), ("attempts", count), ("mode", mode),
                                    ("faults", faults), ("request_id", "exp26-" + name), ("generation_id", "g0")):
                self.check(case.get(field) == expected, "plan_" + field, name)
            self.check(case.get("idempotency_key") == (None if name == "no-key" else "safe-text-" + name), "plan_key", name)
        return indexed

    def time_bounds(self, row, context):
        start, end = row.get("started_ns"), row.get("ended_ns")
        self.check(type(start) is int and type(end) is int and 0 <= start <= end, "time_bounds", context)

    def request(self, case, row, client):
        name, rid = case["case_id"], case["request_id"]
        count = EXPECTED[name][1]
        for field in ("case_id", "request_id", "generation_id", "mode", "idempotency_key", "terminal"):
            self.check(row.get(field) == case.get(field), "gateway_" + field, name)
        self.check(client.get("case_id") == name, "client_case", name)
        self.check(client.get("request_id") == rid, "client_request_id", name)
        self.time_bounds(row, name); self.time_bounds(client, name + ":client")
        self.check(not client.get("error_type") and not client.get("error"), "client_error", name)
        attempts, settlements, events = row.get("attempts"), row.get("settlements"), row.get("events")
        for value, label in ((attempts, "attempts"), (settlements, "settlements"), (events, "events")):
            if not self.check(isinstance(value, list) and all(isinstance(v, dict) for v in value), "row_schema", name, label):
                return
        self.check(len(attempts) == count, "attempt_count", name)
        indexed = self.unique(attempts, "attempt_id", name)
        s_indexed = self.unique(settlements, "attempt_id", name + ":settlements")
        self.check(len(settlements) == len(attempts) and set(s_indexed) == set(indexed), "settlement_coverage", name)
        previous_ns = row.get("started_ns", 0)
        for event in events:
            ns = event.get("ns")
            self.check(type(ns) is int and type(previous_ns) is int and ns >= previous_ns, "event_order", name)
            if type(ns) is int:
                previous_ns = ns
            if "attempt_id" in event:
                self.check(event["attempt_id"] in indexed, "event_attempt", name, event["attempt_id"])
        stop_positions = [i for i, e in enumerate(events) if e.get("event") == "stop_requested"]
        self.check(len(stop_positions) <= 1, "duplicate_stop", name)
        stop = stop_positions[0] if stop_positions else None
        if case["terminal"] in ("cancelled", "superseded", "drain_timeout", "client_disconnected"):
            self.check(stop is not None and events[stop].get("reason") == case["terminal"], "stop_reason", name)
        else:
            self.check(stop is None, "unexpected_stop", name)
        starts, sent_events, pending = [], [], None
        for i, event in enumerate(events):
            kind, aid = event.get("event"), event.get("attempt_id")
            if kind == "content_send_started":
                self.check(stop is None or i < stop, "send_started_after_stop", name)
                self.check(pending is None, "overlapping_send", name)
                pending = aid
                starts.append(i)
            elif kind == "content_sent":
                self.check(pending == aid and pending is not None, "send_commit_without_start", name)
                pending = None
                self.check(isinstance(event.get("text"), str) and bool(event["text"]), "sent_text", name)
                sent_events.append((i, event))
        self.check(pending is None, "uncommitted_send", name)
        sent = "".join(e.get("text", "") for _, e in sent_events if isinstance(e.get("text"), str))
        self.check(sent == row.get("sent_content"), "sent_content", name)
        self.check(row.get("committed") is bool(sent_events), "commit_flag", name)
        if count:
            self.check(row.get("sent_sha256") == _sha(sent), "sent_hash", name)
            finished = [e for e in events if e.get("event") == "request_finished"]
            self.check(len(finished) == 1 and finished[0].get("terminal") == case["terminal"], "request_finished", name)
        for index, attempt in enumerate(attempts):
            aid = attempt.get("attempt_id")
            self.check(aid not in self.attempt_ids, "duplicate_global_attempt", name, aid)
            self.attempt_ids.add(aid)
            self.check(aid == rid + f"/a{index + 1}", "attempt_identity", name)
            self.check(attempt.get("request_id") == rid and attempt.get("mode") == case["mode"], "attempt_owner", str(aid))
            self.check(attempt.get("worker_joined") is True, "worker_not_joined", str(aid))
            self.time_bounds(attempt, str(aid))
            fault = (case["faults"] + [None, None])[index] if index < 2 else "extra"
            self.check(attempt.get("injected_fault") == fault, "attempt_fault", str(aid))
            positions = {}
            for kind in ("attempt_started", "worker_exited", "attempt_joined"):
                found = [i for i, e in enumerate(events) if e.get("event") == kind and e.get("attempt_id") == aid]
                self.check(len(found) == 1, "attempt_lifecycle", str(aid), kind)
                positions[kind] = found[0] if found else -1
            self.check(positions["attempt_started"] < positions["worker_exited"] < positions["attempt_joined"], "join_order", str(aid))
            for i, e in sent_events:
                if e.get("attempt_id") == aid:
                    self.check(positions["attempt_started"] < i < positions["attempt_joined"], "send_lifecycle", str(aid))
            generated = "".join(e.get("text", "") for e in events if e.get("event") == "generated" and e.get("attempt_id") == aid)
            self.check(generated == attempt.get("generated_content"), "generated_content", str(aid))
            delivered = "".join(e.get("text", "") for _, e in sent_events if e.get("attempt_id") == aid)
            self.check(generated.startswith(delivered), "delivered_generation", str(aid))
            if index:
                previous = attempts[index - 1]
                prior_id = previous.get("attempt_id")
                prior_join = [i for i, e in enumerate(events) if e.get("event") == "attempt_joined" and e.get("attempt_id") == prior_id]
                retry = [i for i, e in enumerate(events) if e.get("event") == "retry_allowed" and e.get("from_attempt") == prior_id]
                self.check(len(retry) == 1 and bool(prior_join) and prior_join[0] < retry[0] < positions["attempt_started"], "retry_order", name)
                self.check(not any(i < positions["attempt_started"] for i, _ in sent_events), "retry_after_commit", name)
                self.check(isinstance(row.get("idempotency_key"), str) and bool(row["idempotency_key"].strip()), "retry_without_key", name)
                self.check(previous.get("outcome") in ("connect_refused", "first_content_timeout", "backend_http_error", "incomplete_stream"), "nonretryable_outcome", name)
                self.check(type(previous.get("ended_ns")) is int and type(attempt.get("started_ns")) is int and previous["ended_ns"] <= attempt["started_ns"], "retry_overlap", name)
            usage, source = attempt.get("usage"), attempt.get("usage_source")
            self.check(usage is None or _valid_usage(usage), "invalid_usage", str(aid))
            expected_source = "unknown" if usage is None else ("native_stream_usage" if case["mode"] == "gpu" else "synthetic_fixture")
            self.check(source == expected_source, "usage_source", str(aid))
            settlement = s_indexed.get(aid)
            self.check(settlement == {"attempt_id": aid, "usage": usage, "source": source}, "settlement_value", str(aid))
            native = parse_native_sse(attempt.get("raw_sse", "")) if case["mode"] == "gpu" else None
            entry = dict(case_id=name, request_id=rid, attempt_id=aid, mode=case["mode"],
                         outcome=attempt.get("outcome"), usage=usage, usage_source=source,
                         settlement=settlement, native_usage=native["usage"] if native else None,
                         usage_known=usage is not None, resource_usage=usage, resource_usage_source=source)
            self.ledger.append(entry)
            if native:
                self.check(not native["errors"], "native_sse", str(aid), native["errors"])
                self.check(native["usage"] == usage, "native_usage", str(aid))
                self.check(native["content"].startswith(attempt.get("generated_content", "")), "native_generated_prefix", str(aid))
                if attempt.get("outcome") == "completed":
                    self.check(native["complete"] and native["finish"] == attempt.get("finish"), "native_complete", str(aid))
                    self.check(native["content"] == attempt.get("generated_content"), "native_generated_full", str(aid))
            if index == len(attempts) - 1 and case["terminal"] == "completed":
                self.check(attempt.get("outcome") == "completed" and attempt.get("finish") in ("stop", "length"), "completed_attempt", str(aid))
        retries = [e for e in events if e.get("event") == "retry_allowed"]
        self.check(len(retries) == max(count - 1, 0), "retry_count", name)
        if case.get("review"):
            self.check(not sent_events, "review_delivery", name)
        if case.get("late"):
            self.check(any(e.get("event") == "late_discard" for e in events), "late_discard", name)
        if case.get("duplicate_settlement"):
            replay = [e for e in events if e.get("event") == "settlement_replayed"]
            self.check(len(replay) == 1 and replay[0].get("inserted") is False, "settlement_replay", name)
        self.client(case, row, client, sent_events)

    def client(self, case, row, client, sent_events):
        name = case["case_id"]
        if case["attempts"] == 0:
            self.check(client.get("status") == 503, "client_status", name)
            try:
                self.check(_json(client.get("raw", "")) == {"request_id": case["request_id"], "error": "draining"}, "drain_rejection", name)
            except (ValueError, TypeError):
                self.check(False, "drain_rejection", name)
            return
        self.check(client.get("status") == 200, "client_status", name)
        parsed = _sse(client.get("raw"))
        self.check(not parsed["errors"], "client_sse", name, parsed["errors"])
        objects = parsed["objects"]
        expected = [dict(type="content", id=case["request_id"], generation_id=case["generation_id"],
                         attempt_id=e["attempt_id"], content=e["text"]) for _, e in sent_events]
        observed = [p for p in objects if p.get("type") == "content"]
        disconnected = name == "gpu-disconnect"
        self.check(client.get("client_closed_intentionally") is disconnected, "intentional_disconnect", name)
        self.check(observed == (expected[:len(observed)] if disconnected else expected), "client_content_packets", name)
        terminal = [p for p in objects if p.get("type") == "terminal"]
        if disconnected:
            self.check(not terminal and parsed["done_count"] == 0, "disconnect_terminal", name)
        else:
            expected_terminal = dict(id=case["request_id"], type="terminal", terminal=case["terminal"], generation_id=case["generation_id"],
                                     attempt_ids=[a.get("attempt_id") for a in row["attempts"]], settlements=row["settlements"],
                                     finish=row["attempts"][-1].get("finish") if case["terminal"] == "completed" and row["attempts"] else None)
            self.check(terminal == [expected_terminal], "client_terminal", name)
            self.check(parsed["done_count"] == 1 and not parsed["tail"].strip(), "client_done", name)
            self.check(parsed["order"] == expected + [expected_terminal, "done"], "client_packet_order", name)
        self.check(all(p.get("type") in ("content", "terminal") for p in objects), "client_packet_type", name)

    def backend(self, rows, gateway):
        http_rows = [r for r in rows if r.get("component") == "backend-http" or ("sse" in r and "attempt_id" in r)]
        indexed = self.unique(http_rows, "attempt_id", "backend-http")
        attempts = {a["attempt_id"]: a for r in gateway for a in r.get("attempts", []) if isinstance(a, dict) and a.get("mode") == "gpu" and "attempt_id" in a}
        expected = set(attempts)  # Every planned GPU attempt needs independent evidence.
        self.check(set(indexed) == expected, "backend_coverage", "backend-http")
        for aid, row in indexed.items():
            attempt = attempts.get(aid)
            if not self.check(attempt is not None, "backend_unknown_attempt", str(aid)):
                continue
            self.check(row.get("request_id") == attempt.get("request_id"), "backend_request_id", str(aid))
            self.check(row.get("status") == attempt.get("http_status"), "backend_status", str(aid))
            body, sse = row.get("body"), row.get("sse")
            self.check(isinstance(body, str) and row.get("request_sha256") == _sha(body), "backend_request_hash", str(aid))
            self.check(isinstance(sse, str) and row.get("response_sha256") == _sha(sse), "backend_response_hash", str(aid))
            try:
                self.check(_json(body) == attempt.get("backend_body"), "backend_body", str(aid))
            except (ValueError, TypeError):
                self.check(False, "backend_body", str(aid))
            self.check(attempt.get("backend_body_sha256") == _sha(_canonical(attempt.get("backend_body"))), "gateway_backend_body_hash", str(aid))
            self.check(isinstance(sse, str) and sse.startswith(attempt.get("raw_sse", "")), "backend_response_prefix", str(aid))
            native = parse_native_sse(sse)
            self.check(not native["errors"], "backend_native_sse", str(aid), native["errors"])
            self.time_bounds(row, str(aid) + ":backend-http")
            for entry in self.ledger:
                if entry["attempt_id"] == aid:
                    entry["backend_http_usage"] = native["usage"]
                    backend_usage = native["usage"]
                    gateway_usage = entry["usage"]
                    if backend_usage is not None and _valid_usage(backend_usage):
                        entry.update(resource_usage=backend_usage, resource_usage_source="backend_http")
                        self.check(gateway_usage == backend_usage, "usage_reconciliation", str(aid),
                                   "backend has valid usage; gateway settlement is missing or differs")
            for field, value in (("request_b64", body), ("response_b64", sse)):
                if field in row:
                    try:
                        decoded = base64.b64decode(row[field], validate=True)
                        self.check(decoded == value.encode("utf-8"), "backend_base64", str(aid), field)
                    except (ValueError, TypeError, AttributeError):
                        self.check(False, "backend_base64", str(aid), field)
            if "send_returned_b64" in row:
                try:
                    returned = base64.b64decode(row["send_returned_b64"], validate=True)
                    self.check(sse.encode("utf-8").startswith(returned), "backend_send_prefix", str(aid))
                except (ValueError, TypeError, AttributeError):
                    self.check(False, "backend_send_prefix", str(aid))
        # Engine hooks have a separate evidence domain. Never promote HTTP close
        # or worker_joined to engine cancellation; the hook schema is independent.
        report = dict(http_rows=len(http_rows), http_evidence="checked" if http_rows else "absent_optional",
                    engine_abort_evidence="unknown", non_http_rows=len(rows) - len(http_rows),
                    scope="HTTP transport evidence does not establish engine abort or GPU kernel stop")
        if any(r.get("schema") == "exp26.backend.v1" or "engine_request_ids" in r for r in rows):
            report.update(self.native_backend(rows, indexed, attempts))
        else:
            self.check(self.evidence_profile == "http_fixture" or not expected,
                       "native_evidence_required", "backend", "formal GPU attempts require native hooks")
            self.check(len(http_rows) == len(rows), "unsupported_backend_schema", "backend")
        return report

    def native_backend(self, rows, http, attempts):
        """CPU hooks, mapping and scheduler observations; no kernel-stop inference.

        Compare timestamps only inside the same backend clock domain. Native
        request overlap is reported separately from sequential gateway workers.
        """
        initial_errors = len(self.errors)
        installed = [r for r in rows if r.get("event") == "hooks_installed"]
        self.check(len(installed) == 1, "native_hooks", "backend")
        install = installed[0] if installed else {}
        self.check(install.get("installed") is True and install.get("vllm_version") == "0.8.5", "native_version", "backend")
        needed = {"AsyncLLMEngine.add_request", "AsyncLLMEngine.abort", "AsyncLLMEngine._abort",
                  "RequestTracker.abort_request", "RequestTracker.process_request_output", "LLMEngine.abort_request",
                  "LLMEngine.step", "_AsyncLLMEngine.step_async", "AsyncLLMEngine.engine_step"}
        self.check(needed <= set(install.get("hooks", [])), "native_hooks", "backend")
        domain, previous_ns = install.get("clock_domain"), -1
        supported = {"hooks_installed", "http_started", "http_request_chunk", "http_response_start", "http_response_chunk",
                     "http_disconnect", "http_send_raised", "http_finished", "engine_request", "engine_child_request",
                     "engine_output", "engine_finished", "add_returned", "add_raised", "abort_called", "abort_returned",
                     "abort_raised", "abort_done", "state_before", "state_after"}
        by_attempt, bindings, http_ids = {}, {}, {}
        for i, row in enumerate(rows):
            aid, event = row.get("attempt_id"), row.get("event")
            self.check(row.get("schema") == "exp26.backend.v1", "native_schema", str(aid))
            self.check(row.get("clock_domain") == domain and isinstance(domain, str), "native_clock", str(aid))
            self.check(row.get("pid") == install.get("pid"), "native_pid", str(aid))
            ns = row.get("backend_monotonic_ns")
            self.check(type(ns) is int and ns >= previous_ns, "native_event_order", str(aid))
            if type(ns) is int: previous_ns = ns
            self.check(row.get("audit_errors", 0) == 0, "native_audit_errors", str(aid))
            self.check(event in supported, "native_observation_error", str(aid), event)
            if aid is None:
                self.check(event == "hooks_installed", "native_identity", "backend", event)
                continue
            if not self.check(aid in attempts, "native_unknown_attempt", str(aid)):
                continue
            self.check(row.get("request_id") == attempts[aid].get("request_id"), "native_request_id", str(aid))
            identity = http.get(aid, {})
            self.check(row.get("http_id") == identity.get("http_id") and isinstance(row.get("http_id"), str), "native_http_id", str(aid))
            by_attempt.setdefault(aid, []).append((i, row))
            eid = row.get("engine_request_id")
            if event in ("engine_request", "engine_child_request"):
                if self.check(isinstance(eid, str) and bool(eid), "native_engine_id", str(aid)):
                    self.check(eid not in bindings, "native_duplicate_binding", str(aid), eid)
                    bindings[eid] = aid
            if event == "http_started":
                hid = row.get("http_id")
                self.check(hid not in http_ids, "native_duplicate_http", str(aid))
                http_ids[hid] = aid
        engine_attempts, starts, clears = [], {}, {}
        for aid, attempt in attempts.items():
            events = by_attempt.get(aid, [])
            h = http.get(aid, {})
            start_events = [(i, r) for i, r in events if r.get("event") == "http_started"]
            self.check(len(start_events) == 1 and h.get("event") == "http_finished", "native_http_lifecycle", aid)
            roots = [(i, r) for i, r in events if r.get("event") == "engine_request"]
            engine_ids = h.get("engine_request_ids", [])
            self.check(isinstance(engine_ids, list) and len(engine_ids) == len(set(engine_ids)) == 1,
                       "native_http_engine_ids", aid)
            self.check(len(roots) == 1 and [r.get("engine_request_id") for _, r in roots] == engine_ids, "native_engine_binding", aid)
            for _, r in events:
                if "engine_request_id" in r:
                    self.check(bindings.get(r["engine_request_id"]) == aid, "native_engine_owner", aid)
            if roots:
                starts[aid] = roots[0][1]["backend_monotonic_ns"]
                self.check(bool(start_events) and start_events[0][0] < roots[0][0], "native_bind_order", aid)
            finished = [r for _, r in events if r.get("event") == "engine_finished" and r.get("finished") is True]
            called = [(i, r) for i, r in events if r.get("event") == "abort_called"]
            returned = [(i, r) for i, r in events if r.get("event") == "abort_returned" and r.get("error") is None]
            for _, r in returned:
                self.check(any(x.get("hook") == r.get("hook") and x.get("engine_request_id") == r.get("engine_request_id")
                               and x["backend_monotonic_ns"] <= r["backend_monotonic_ns"] for _, x in called), "native_abort_order", aid)
            for _, r in called:
                self.check(any(x.get("hook") == r.get("hook") and x.get("engine_request_id") == r.get("engine_request_id")
                               and x["backend_monotonic_ns"] >= r["backend_monotonic_ns"] for _, x in returned), "native_abort_return", aid)
            abort_done = [r for _, r in events if r.get("event") == "abort_done"]
            for r in abort_done:
                self.check(any(x.get("hook") == r.get("hook") and x["backend_monotonic_ns"] <= r["backend_monotonic_ns"] for _, x in returned), "native_abort_done", aid)
            snapshots = [r for _, r in events if r.get("event") == "state_after" and r.get("snapshot_complete") is True]
            clean = []
            for r in snapshots:
                queues, cached, tracker = r.get("queues"), r.get("cached"), r.get("tracker")
                if not self.check(isinstance(queues, list) and isinstance(cached, list) and (tracker is None or isinstance(tracker, dict)), "native_state_schema", aid):
                    continue
                scheduler_pending = any(q.get("unfinished") is True for q in queues)
                engine_pending = scheduler_pending or any(q.get("remaining_steps", 0) > 0 for q in cached)
                self.check(r.get("scheduler_unfinished") is scheduler_pending and r.get("engine_pending_or_unfinished") is engine_pending, "native_state_flags", aid)
                if isinstance(tracker, dict):
                    self.check(set(tracker) == {"active_stream", "new_pending", "abort_pending"} and all(type(v) is bool for v in tracker.values()), "native_tracker", aid)
                    self.check(r.get("pending_or_unfinished") is (engine_pending or any(tracker.values())), "native_pending_flags", aid)
                if (r.get("pending_or_unfinished") is False and not engine_pending and isinstance(tracker, dict)
                        and not any(tracker.values()) and r.get("error") is None):
                    clean.append(r)
            quiescent = bool(snapshots) and bool(clean) and snapshots[-1] in clean
            self.check(quiescent, "native_not_quiescent", aid)
            if attempt.get("outcome") == "completed":
                self.check(bool(finished), "native_finish_missing", aid)
            else:
                self.check(bool(finished) or bool(called) and bool(returned), "native_abort_missing", aid)
            terminal_ns = max([r["backend_monotonic_ns"] for _, r in returned] + [r["backend_monotonic_ns"] for r in finished] + [-1])
            clean_after = [r for r in clean if r["backend_monotonic_ns"] >= terminal_ns]
            self.check(bool(clean_after), "native_final_snapshot", aid)
            if clean_after:
                clears[aid] = clean_after[0]["backend_monotonic_ns"]
            engine_attempts.append(dict(attempt_id=aid, engine_request_ids=engine_ids, http_id=h.get("http_id"),
                                        engine_finished=bool(finished), abort_called=bool(called),
                                        abort_returned=bool(returned), abort_done_observed=bool(abort_done),
                                        scheduler_quiescent=quiescent, gpu_kernel_stopped="unknown"))
        overlap = []
        for aid in attempts:
            if aid.endswith("/a2"):
                previous = aid[:-1] + "1"
                overlap.append(dict(previous_attempt_id=previous, attempt_id=aid,
                                    previous_engine_quiescent_before_next=(clears[previous] <= starts[aid])
                                    if previous in clears and aid in starts else None,
                                    evidence="same backend monotonic clock; CPU scheduler/tracker only"))
        return dict(engine_abort_evidence="checked_cpu_hooks" if len(self.errors) == initial_errors else "invalid_cpu_hooks",
                    engine_attempts=engine_attempts, native_retry_order=overlap, gpu_kernel_stopped="unknown")

    def run(self):
        plan = self.load("plan.json")
        gateway, clients, backend, health = [self.load(name, rows=True) for name in ("gateway.jsonl", "clients.json", "backend.jsonl", "health.json")]
        cases = self.audit_plan(plan)
        self.provenance(plan, gateway)
        g = self.unique(gateway, "case_id", "gateway")
        c = self.unique(clients, "case_id", "clients")
        h = self.unique(health, "case_id", "health")
        self.unique(gateway, "request_id", "gateway")
        self.unique(clients, "request_id", "clients")
        for indexed, label, rows in ((g, "gateway", gateway), (c, "clients", clients), (h, "health", health)):
            self.check(set(indexed) == set(EXPECTED) and len(rows) == 17, "case_coverage", label)
        for name in EXPECTED:
            state = h.get(name, {}).get("state", {})
            self.check(state.get("active") == 0 and state.get("workers") == 0, "not_quiescent", name)
            if name in cases and name in g and name in c:
                try:
                    self.request(cases[name], g[name], c[name])
                except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
                    self.check(False, "row_schema", name, exc)
        try:
            backend_report = self.backend(backend, gateway)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            self.check(False, "backend_schema", "backend", exc)
            backend_report = dict(engine_abort_evidence="unknown")
        accepted = not self.errors
        metrics = None
        if accepted:
            metrics = {}
            for mode in ("gpu", "controlled"):
                ledger = [a for a in self.ledger if a["mode"] == mode]
                known = [a for a in ledger if a["usage"] is not None]
                metrics[mode] = dict(attempts=len(ledger), known_usage_attempts=len(known),
                                     unknown_usage_attempts=len(ledger) - len(known),
                                     **{"known_" + field: sum(a["usage"][field] for a in known) for field in TOKEN_FIELDS})
            metrics["matched_requests"] = 17
        report = dict(schema=1, experiment="exp26", accepted=accepted, planned=17, evidence_profile=self.evidence_profile,
                      auditor_sha256=_sha(Path(__file__).read_bytes()),
                      frozen_source_sha256=plan.get("source_sha256", {}),
                      planned_modes={"controlled": 12, "gpu": 5}, planned_attempts=19,
                      errors=self.errors, metrics=metrics, attempt_ledger=self.ledger, backend=backend_report,
                      observed=dict(gateway_rows=len(gateway), client_rows=len(clients), backend_rows=len(backend),
                                    terminal_counts=dict(Counter(str(r.get("terminal")) for r in gateway))),
                      scope="Controlled faults; same physical GPU; native known-token subtotal is not complete cost or currency billing")
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return report


def analyze(out, summary_path=None, evidence_profile="formal_native"):
    return _Audit(out, summary_path, evidence_profile).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--summary", type=Path, help="optional revision output; default OUT/summary.json")
    args = parser.parse_args()
    report = analyze(args.out, args.summary)
    print(json.dumps({"accepted": report["accepted"], "errors": len(report["errors"]),
                      "summary": str(args.summary or args.out / "summary.json")}))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
