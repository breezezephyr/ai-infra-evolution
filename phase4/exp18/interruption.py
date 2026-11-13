"""Recompute exp16 interruption evidence, offline, using only raw JSON files.

API: extract(root: Path) -> JSON-serializable dict; root is phase4.
CLI: python3 -B phase4/exp18/interruption.py phase4
No model imports, network access, output files, or summary.json dependencies.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


POLICIES = ("server_only", "full")
POINTS_MS = (200, 1000, 4000)
BROWSER = Path("results/exp16/browser-formal-v1/records.json")
SERVERS = Path("results/exp16/server/final-v1")


def _obj(value):
    return value if isinstance(value, dict) else {}


def _integer(value):
    return type(value) is int and value >= 0


def _rate(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _read(root, path, sources, issues):
    source = {"path": path.as_posix(), "sha256": None, "status": "missing"}
    sources.append(source)
    try:
        raw = (root / path).read_bytes()
    except OSError as exc:
        source["status"] = "missing" if isinstance(exc, FileNotFoundError) else "unreadable"
        issues.append(f"{path}: {source['status']}")
        return {}
    source["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
    except (ValueError, UnicodeError) as exc:
        source["status"] = "invalid"
        issues.append(f"{path}: invalid JSON object ({exc})")
        return {}
    source["status"] = "ok"
    return data


def _server_delta(server, run, issues):
    events = _obj(_obj(server.get("generations")).get("1")).get("events")
    if isinstance(events, list):
        stops = [e for e in events if _obj(e).get("event") == "stop_signal_set"]
        joins = [e for e in events if _obj(e).get("event") == "workers_joined"]
        if len(stops) == len(joins) == 1:
            stop, join = stops[0], joins[0]
            if all(e.get("clock_domain") == "server_monotonic"
                   and e.get("generation_id") == 1 and e.get("session_id") == run
                   and _integer(e.get("monotonic_ns")) for e in (stop, join)):
                delta = join["monotonic_ns"] - stop["monotonic_ns"]
                if delta >= 0 and join.get("llm_stopped") is True and join.get("tts_stopped") is True:
                    return delta / 1_000_000
    issues.append("server stop/join endpoints missing, ambiguous, out of order, or wrong clock/identity")
    return None


def _probes(record):
    events = record.get("events")
    if not isinstance(events, list):
        return None
    events = [e for e in events if isinstance(e, dict) and e.get("generation") == 1]
    received = [e for e in events if e.get("event") == "stale_probe_received"
                and e.get("source") == "server" and e.get("controlled") is True]
    # exp16 has no probe id: match the generation, stream offset, and sample length.
    keys = {(e.get("offset"), e.get("samples")) for e in received
            if _integer(e.get("offset")) and _integer(e.get("samples")) and e["samples"] > 0}
    worklet = [e for e in events if e.get("source") == "worklet"
               and e.get("stale_probe") is True and (e.get("offset"), e.get("samples")) in keys]
    fenced = sum(e.get("event") == "rejected" and e.get("reason") == "generation_fence"
                 for e in worklet)
    accepted = sum(e.get("event") == "enqueued" for e in worklet)
    ignored = sum(e.get("event") == "ignored_controlled_probe" and e.get("source") == "client"
                  and (e.get("offset"), e.get("samples")) in keys for e in events)
    return {"received_events": len(received), "generation_fence_events": fenced,
            "accepted_events": accepted, "ignored_events": ignored,
            "all_fenced": bool(received) and fenced == len(received) and accepted == 0}


def _new_generation(record, server):
    g = _obj(_obj(record.get("generations")).get("2"))
    values = [g.get(k) for k in ("played", "sent", "received_samples", "accepted", "queued", "discarded")]
    values += [_obj(server.get("sent")).get("2"), _obj(server.get("playback")).get("2")]
    if not all(_integer(v) for v in values) or type(g.get("done")) is not bool:
        return None
    played, sent, received, accepted, queued, discarded, server_sent, server_played = values
    return (played > 0 and played == sent == received == accepted == server_sent == server_played
            and queued == discarded == 0 and g["done"])


def _history(record, server):
    generations = _obj(server.get("generations"))
    segments = _obj(generations.get("1")).get("segments")
    prompt = _obj(_obj(_obj(generations.get("2")).get("state")).get("llm")).get("prompt_messages")
    played = _obj(server.get("playback")).get("1")
    client_played = _obj(_obj(record.get("generations")).get("1")).get("played")
    if not (_integer(played) and _integer(client_played) and isinstance(segments, list)
            and isinstance(prompt, list)):
        return None
    if not all(isinstance(s, dict) and _integer(s.get("start")) and _integer(s.get("end"))
               and s["end"] > s["start"] and isinstance(s.get("text"), str) for s in segments):
        return None
    if not all(isinstance(m, dict) and isinstance(m.get("role"), str)
               and isinstance(m.get("content"), str) for m in prompt):
        return None
    complete = [s for s in segments if s["end"] <= played]
    expected = "".join(s["text"] for s in complete)
    assistant = [m["content"] for m in prompt if m["role"] == "assistant"]
    matches = assistant == ([expected] if expected else []) and played == client_played
    return {"played_samples": played, "complete_segments": len(complete),
            "expected_text": expected, "assistant_messages": assistant,
            "status": ("complete_segments" if expected else "empty") if matches else "mismatch"}


def _case(record, server, server_path):
    issues = []
    run = record["run_id"]
    # Never fall back to client_result embedded in a server file, or receive timestamps.
    paired = server.get("run_id") == run and server.get("policy") == record.get("policy")
    if not paired:
        issues.append("matching server run_id/policy unavailable")
        server = {}
    rate = record.get("context_rate")
    trigger = _obj(record.get("trigger"))
    old = _obj(_obj(record.get("generations")).get("1"))
    start, end = trigger.get("frame"), old.get("last_render_end_frame")
    render_tail = None
    if (_rate(rate) and _integer(start) and _integer(end) and end >= start
            and trigger.get("generation") == 1
            and all(e.get("sample_rate", rate) == rate for e in (trigger, old))):
        render_tail = (end - start) * 1000 / rate
    else:
        issues.append("render-tail frame endpoints or matching context_rate unavailable")
    samples = record.get("trigger_samples")
    point = samples * 1000 / rate if _integer(samples) and _rate(rate) else None
    point = next((p for p in POINTS_MS if point is not None and math.isclose(point, p)), None)
    if point is None:
        issues.append("trigger point outside the 200/1000/4000 ms design or missing context_rate")
    new = _new_generation(record, server)
    history = _history(record, server)
    probes = _probes(record)
    if new is None:
        issues.append("generation 2 PCM counters or completion evidence missing")
    elif not new:
        issues.append("generation 2 PCM not fully rendered or counters inconsistent")
    if history is None or history["status"] == "mismatch":
        issues.append("complete-segment history/prompt evidence missing or inconsistent")
    if record.get("policy") == "full" and (probes is None or not probes["all_fenced"]):
        issues.append("controlled stale probe generation_fence evidence missing or inconsistent")
    return {"run_id": run, "policy": record.get("policy"), "point_ms": point,
            "trigger_samples": samples, "context_rate": rate,
            "trigger_frame": start, "g1_last_render_end_frame": end,
            "render_tail_ms": render_tail,
            "server_stop_to_workers_joined_ms": _server_delta(server, run, issues),
            "server_source": server_path.as_posix(), "server_paired": paired,
            "controlled_stale_probe": probes, "new_generation_fully_played": new,
            "assistant_history": history, "issues": issues}


def _distribution(values, denominator):
    values = sorted(v for v in values if v is not None)

    def percentile(q):
        if not values:
            return None
        index = (len(values) - 1) * q
        low, high = math.floor(index), math.ceil(index)
        return values[low] + (values[high] - values[low]) * (index - low)

    return {"n": len(values), "denominator": denominator, "missing": denominator - len(values),
            "values_ms": values, "min_ms": values[0] if values else None,
            "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "max_ms": values[-1] if values else None,
            "mean_ms": sum(values) / len(values) if values else None}


def _all_observed(values, expected_n):
    if any(v is False for v in values):
        return False
    return True if expected_n > 0 and len(values) == expected_n and all(v is True for v in values) else None


def _group(cases, expected_n, expected_probes):
    n = len(cases)
    full = [c["controlled_stale_probe"] for c in cases if c["policy"] == "full"]
    probes = [p for p in full if p is not None]
    next_audio = [c["new_generation_fully_played"] for c in cases]
    histories = [c["assistant_history"] for c in cases if c["assistant_history"] is not None]
    return {
        "n": n, "expected_n": expected_n,
        "render_tail_ms": _distribution([c["render_tail_ms"] for c in cases], n),
        "server_stop_to_workers_joined_ms": _distribution(
            [c["server_stop_to_workers_joined_ms"] for c in cases], n),
        "controlled_stale_probe": {
            "denominator": len(full), "expected_n": expected_probes, "missing": len(full) - len(probes),
            "received_cases": sum(p["received_events"] > 0 for p in probes),
            "received_events": sum(p["received_events"] for p in probes),
            "generation_fence_cases": sum(p["all_fenced"] for p in probes),
            "generation_fence_events": sum(p["generation_fence_events"] for p in probes),
            "accepted_events": sum(p["accepted_events"] for p in probes),
            "all_fenced": _all_observed([p["all_fenced"] if p else None for p in full], expected_probes),
        },
        "new_generation": {
            "denominator": n, "expected_n": expected_n,
            "fully_played_cases": sum(v is True for v in next_audio),
            "not_fully_played_cases": sum(v is False for v in next_audio),
            "missing": sum(v is None for v in next_audio),
            "all_fully_played": _all_observed(next_audio, expected_n),
        },
        "assistant_history": {
            "denominator": n, "expected_n": expected_n, "missing": n - len(histories),
            "complete_segment_cases": sum(h["status"] == "complete_segments" for h in histories),
            "complete_segments": sum(h["complete_segments"] for h in histories
                                     if h["status"] == "complete_segments"),
            "empty_cases": sum(h["status"] == "empty" for h in histories),
            "mismatch_cases": sum(h["status"] == "mismatch" for h in histories),
        },
    }


def extract(root: Path) -> dict:
    """Return auditable measurements; absent evidence stays null, never zero/success.

    Source paths are relative to root, with SHA-256 over exact source bytes.
    Distribution n counts measured cases; denominator counts unique browser cases;
    expected_n records the fixed design even when records are absent. Quantiles use
    linear interpolation at (n-1)*q. No derived latency/validity/stale summaries are read.
    """
    root = Path(root)
    sources, issues, cases = [], [], []
    browser = _read(root, BROWSER, sources, issues)
    records = browser.get("records", [])
    if not isinstance(records, list):
        issues.append("browser records is not a list")
        records = []
    seen = set()
    for index, record in enumerate(records):
        run = _obj(record).get("run_id")
        if not isinstance(run, str) or re.fullmatch(r"[A-Za-z0-9_-]+", run) is None:
            issues.append(f"browser record {index}: missing or unsafe run_id")
            continue
        if run in seen:
            issues.append(f"duplicate browser run_id: {run}")
            continue
        seen.add(run)
        server_path = SERVERS / f"server-{run}.json"
        server = _read(root, server_path, sources, issues)
        cases.append(_case(record, server, server_path))
    groups = []
    for policy in POLICIES:
        for point in POINTS_MS:
            selected = [c for c in cases if c["policy"] == policy and c["point_ms"] == point]
            groups.append({"policy": policy, "point_ms": point,
                           **_group(selected, 3, 3 if policy == "full" else 0)})
    paired = sum(c["server_paired"] for c in cases)
    complete = not issues and len(cases) == paired == 18 and all(g["n"] == 3 for g in groups)
    return {
        "schema_version": "exp18.interruption.v1", "source_root": str(root.resolve()),
        "sources": sources, "issues": issues,
        "definitions": {
            "render_tail_ms": "(g1.last_render_end_frame - trigger.frame) * 1000 / context_rate; exclusive AudioContext frame boundaries",
            "server_stop_to_workers_joined_ms": "(g1.workers_joined.monotonic_ns - g1.stop_signal_set.monotonic_ns) / 1e6; server_monotonic only",
            "controlled_stale_probe": "full cases only; controlled receive matched to worklet stale_probe generation_fence by generation/offset/samples; ordinary late frames excluded",
            "new_generation": "generation 2 positive played=sent=received=accepted=server.sent=server.playback, done=true, queued=discarded=0",
            "assistant_history": "server g1 segments with end <= reported playback; compare their concatenated text to actual g2 assistant prompt messages",
            "quantiles": "linear interpolation at (n-1)*q; values_ms contains every measured case",
            "scope": "explicit playback-position trigger; render consumption proxy, no microphone onset, VAD, acoustic stop, or client/server clock subtraction",
        },
        "coverage": {"expected_cases": 18, "browser_records": len(records),
                     "unique_browser_cases": len(cases), "server_pairs": paired,
                     "complete_design": complete},
        "overall": _group(cases, 18, 9),
        "by_policy": {p: _group([c for c in cases if c["policy"] == p], 9, 9 if p == "full" else 0)
                      for p in POLICIES},
        "by_policy_and_point": groups, "cases": cases,
        "unmeasured": {"microphone_onset_ms": None, "vad_latency_ms": None,
                       "acoustic_stop_latency_ms": None},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    print(json.dumps(extract(parser.parse_args().root), ensure_ascii=False, indent=2, allow_nan=False))
