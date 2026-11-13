"""Local, model-free tests for the exp16 raw-data extractor."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).with_name("interruption.py")
if MODULE.exists():
    spec = importlib.util.spec_from_file_location("exp18_interruption", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extract = module.extract
else:
    extract = None


class InterruptionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(extract), "extract(root: Path) has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "phase4"
        self.browser_path = self.root / "results/exp16/browser-formal-v1/records.json"
        self.servers = self.root / "results/exp16/server/final-v1"
        self.browser_path.parent.mkdir(parents=True)
        self.servers.mkdir(parents=True)
        self.records = []
        self.server_data = {}
        for policy in ("server_only", "full"):
            for point in (200, 1000, 4000):
                for repeat in range(3):
                    run = f"{policy}-{point}-{repeat}"
                    played = 10 if point == 4000 else 5
                    text = "A" if point == 4000 else ""
                    segments = [
                        {"generation": 1, "segment": 0, "start": 0, "end": 10, "text": "A"},
                        {"generation": 1, "segment": 1, "start": 10, "end": 20, "text": "B"},
                    ]
                    events = [{"event": "stale_probe_received", "source": "server",
                               "generation": 1, "controlled": True, "offset": 100, "samples": 480}]
                    if policy == "full":
                        events += [
                            {"event": "rejected", "source": "worklet", "generation": 1,
                             "stale_probe": True, "reason": "generation_fence", "offset": 100,
                             "samples": 480},
                            # A real late frame must not inflate the controlled probe count.
                            {"event": "rejected", "source": "worklet", "generation": 1,
                             "stale_probe": False, "reason": "generation_fence", "offset": 200,
                             "samples": 480},
                        ]
                    else:
                        events.append({"event": "ignored_controlled_probe", "source": "client",
                                       "generation": 1, "offset": 100, "samples": 480})
                    self.records.append({
                        "run_id": run, "policy": policy, "repeat": repeat,
                        "trigger_samples": point * 24, "context_rate": 24000,
                        "requested_sample_rate": 24000,
                        "trigger": {"generation": 1, "frame": 1000, "sample_rate": 24000,
                                    "notification_performance_ms": -999999},
                        "generations": {
                            "1": {"played": played, "last_render_end_frame": 1048,
                                  "sample_rate": 24000},
                            "2": {"played": 100, "sent": 100, "received_samples": 100,
                                  "accepted": 100, "queued": 0, "discarded": 0, "done": True},
                        },
                        "events": events,
                        # Derived summaries and copied history are deliberately wrong.
                        "trigger_to_last_old_render_ms": 999999,
                        "last_old_render_end_frame": 999999,
                        "stale_fence_rejection_count": 999,
                        "history": [{"text": "untrusted summary"}],
                    })
                    self.server_data[run] = {
                        "run_id": run, "policy": policy, "sent": {"1": 100, "2": 100},
                        "playback": {"1": played, "2": 100},
                        "generations": {
                            "1": {"segments": segments, "events": [
                                {"event": "stop_signal_set", "clock_domain": "server_monotonic",
                                 "monotonic_ns": 10**15, "generation_id": 1, "session_id": run},
                                {"event": "workers_joined", "clock_domain": "server_monotonic",
                                 "monotonic_ns": 10**15 + 5_000_000, "generation_id": 1,
                                 "session_id": run, "llm_stopped": True, "tts_stopped": True},
                            ]},
                            "2": {"state": {"llm": {"prompt_messages": [
                                {"role": "system", "content": "system"},
                                *([{"role": "assistant", "content": text}] if text else []),
                                {"role": "user", "content": "next"},
                            ]}}},
                        },
                    }

    def write(self):
        self.browser_path.write_text(json.dumps({"records": self.records,
                                                "completed_runs": 777, "failed_runs": 888}))
        for run, data in self.server_data.items():
            (self.servers / f"server-{run}.json").write_text(json.dumps(data))

    def result(self):
        self.write()
        return extract(self.root)

    def test_raw_records_define_denominators_and_ignore_summaries(self):
        out = self.result()
        self.assertEqual(out["overall"]["n"], 18)
        self.assertTrue(out["coverage"]["complete_design"])
        for group in out["by_policy"].values():
            self.assertEqual(group["n"], 9)
            self.assertEqual(group["render_tail_ms"]["n"], 9)
            self.assertEqual(group["render_tail_ms"]["p50_ms"], 2)
        self.assertEqual(len(out["by_policy_and_point"]), 6)
        self.assertTrue(all(g["n"] == 3 for g in out["by_policy_and_point"]))
        probes = out["by_policy"]["full"]["controlled_stale_probe"]
        self.assertEqual(probes["denominator"], 9)
        self.assertEqual(probes["received_cases"], 9)
        self.assertEqual(probes["generation_fence_cases"], 9)
        self.assertEqual(probes["generation_fence_events"], 9)
        self.assertEqual(probes["accepted_events"], 0)
        self.assertTrue(probes["all_fenced"])

    def test_context_rate_is_the_render_tail_divisor(self):
        # 96 frames / 48000 Hz = 2 ms, despite requested_sample_rate=24000.
        r = self.records[0]
        r["context_rate"] = 48000
        r["trigger_samples"] = 9600
        r["trigger"]["sample_rate"] = 48000
        r["generations"]["1"].update(last_render_end_frame=1096, sample_rate=48000)
        out = self.result()
        self.assertEqual(out["cases"][0]["render_tail_ms"], 2)
        self.assertEqual(out["cases"][0]["point_ms"], 200)

    def test_absolute_client_and_server_clock_offsets_do_not_change_deltas(self):
        before = self.result()
        for r in self.records:
            r["trigger"]["notification_performance_ms"] = 10**20
            r["events"].append({"event": "workers_joined", "source": "server",
                                "performance_ms": -10**20, "generation": 1})
        for s in self.server_data.values():
            for e in s["generations"]["1"]["events"]:
                e["monotonic_ns"] += 10**18
        after = self.result()
        self.assertEqual(after["overall"]["render_tail_ms"], before["overall"]["render_tail_ms"])
        self.assertEqual(after["overall"]["server_stop_to_workers_joined_ms"],
                         before["overall"]["server_stop_to_workers_joined_ms"])
        self.assertEqual(after["overall"]["server_stop_to_workers_joined_ms"]["p50_ms"], 5)

    def test_missing_or_wrong_server_clock_is_not_replaced_by_client_timestamps(self):
        run = self.records[0]["run_id"]
        events = self.server_data[run]["generations"]["1"]["events"]
        for domain in (None, "client_performance", "other_server_monotonic"):
            with self.subTest(domain=domain):
                events[1]["clock_domain"] = domain
                out = self.result()
                self.assertIsNone(out["cases"][0]["server_stop_to_workers_joined_ms"])
                self.assertEqual(out["overall"]["server_stop_to_workers_joined_ms"]["n"], 17)
                self.assertEqual(out["overall"]["server_stop_to_workers_joined_ms"]["missing"], 1)

    def test_missing_browser_is_unknown_not_success(self):
        out = extract(self.root)
        self.assertEqual(out["overall"]["n"], 0)
        self.assertIsNone(out["overall"]["render_tail_ms"]["p50_ms"])
        self.assertIsNone(out["overall"]["new_generation"]["all_fully_played"])
        self.assertFalse(out["coverage"]["complete_design"])
        self.assertEqual(out["sources"][0]["status"], "missing")
        self.assertIsNone(out["sources"][0]["sha256"])

    def test_missing_server_keeps_browser_case_and_visible_denominator(self):
        self.write()
        (self.servers / f"server-{self.records[0]['run_id']}.json").unlink()
        out = extract(self.root)
        self.assertEqual(out["overall"]["n"], 18)
        self.assertEqual(out["overall"]["render_tail_ms"]["n"], 18)
        metric = out["overall"]["server_stop_to_workers_joined_ms"]
        self.assertEqual((metric["n"], metric["denominator"], metric["missing"]), (17, 18, 1))
        self.assertEqual(out["overall"]["new_generation"]["missing"], 1)
        self.assertIsNone(out["overall"]["new_generation"]["all_fully_played"])
        self.assertFalse(out["coverage"]["complete_design"])

    def test_missing_browser_case_does_not_silently_shrink_expected_denominator(self):
        self.records.pop()
        out = self.result()
        self.assertEqual(out["coverage"]["expected_cases"], 18)
        self.assertEqual(out["overall"]["n"], 17)
        self.assertEqual(out["by_policy"]["full"]["n"], 8)
        self.assertEqual(out["by_policy"]["full"]["expected_n"], 9)
        self.assertIsNone(out["by_policy"]["full"]["controlled_stale_probe"]["all_fenced"])
        self.assertIsNone(out["overall"]["new_generation"]["all_fully_played"])

    def test_new_generation_requires_positive_conserved_audio_and_server_agreement(self):
        g2 = self.records[0]["generations"]["2"]
        g2["played"] = 99
        out = self.result()
        self.assertEqual(out["overall"]["new_generation"]["fully_played_cases"], 17)
        self.assertEqual(out["overall"]["new_generation"]["not_fully_played_cases"], 1)
        self.assertFalse(out["overall"]["new_generation"]["all_fully_played"])
        g2.pop("played")
        out = self.result()
        self.assertIsNone(out["cases"][0]["new_generation_fully_played"])
        self.assertEqual(out["overall"]["new_generation"]["missing"], 1)

    def test_history_uses_only_complete_segment_boundaries_and_actual_prompt(self):
        out = self.result()
        history = out["overall"]["assistant_history"]
        self.assertEqual(history["complete_segment_cases"], 6)
        self.assertEqual(history["complete_segments"], 6)
        self.assertEqual(history["empty_cases"], 12)
        self.assertEqual(history["mismatch_cases"], 0)
        case = out["cases"][6]
        self.assertEqual(case["assistant_history"]["expected_text"], "A")
        run = self.records[6]["run_id"]
        self.server_data[run]["generations"]["2"]["state"]["llm"]["prompt_messages"][1]["content"] = "AB"
        out = self.result()
        self.assertEqual(out["overall"]["assistant_history"]["mismatch_cases"], 1)

    def test_missing_prompt_or_event_log_is_not_counted_as_empty_or_zero(self):
        r = self.records[9]
        r.pop("events")
        self.server_data[r["run_id"]]["generations"]["2"]["state"]["llm"].pop("prompt_messages")
        out = self.result()
        self.assertEqual(out["overall"]["assistant_history"]["missing"], 1)
        self.assertEqual(out["overall"]["assistant_history"]["empty_cases"], 11)
        self.assertEqual(out["by_policy"]["full"]["controlled_stale_probe"]["missing"], 1)
        self.assertIsNone(out["by_policy"]["full"]["controlled_stale_probe"]["all_fenced"])

    def test_negative_or_inconsistent_frame_and_stop_boundaries_are_missing(self):
        self.records[0]["generations"]["1"]["last_render_end_frame"] = 999
        events = self.server_data[self.records[0]["run_id"]]["generations"]["1"]["events"]
        events[1]["monotonic_ns"] = 0
        out = self.result()
        self.assertIsNone(out["cases"][0]["render_tail_ms"])
        self.assertIsNone(out["cases"][0]["server_stop_to_workers_joined_ms"])
        self.assertTrue(out["cases"][0]["issues"])

    def test_duplicate_run_does_not_inflate_case_or_success_counts(self):
        self.records.append(copy.deepcopy(self.records[0]))
        out = self.result()
        self.assertEqual(out["coverage"]["browser_records"], 19)
        self.assertEqual(out["overall"]["n"], 18)
        self.assertFalse(out["coverage"]["complete_design"])
        self.assertTrue(out["issues"])

    def test_sources_have_byte_hashes_and_unmeasured_acoustics_stay_null(self):
        out = self.result()
        self.assertEqual(len(out["sources"]), 19)
        for source in out["sources"]:
            path = self.root / source["path"]
            self.assertEqual(source["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(source["status"], "ok")
        self.assertEqual(out["unmeasured"], {
            "microphone_onset_ms": None, "vad_latency_ms": None,
            "acoustic_stop_latency_ms": None,
        })
        json.dumps(out, allow_nan=False)

    def test_invalid_json_is_reported_with_source_hash(self):
        self.browser_path.write_bytes(b"{broken")
        out = extract(self.root)
        self.assertEqual(out["overall"]["n"], 0)
        self.assertEqual(out["sources"][0]["status"], "invalid")
        self.assertEqual(out["sources"][0]["sha256"],
                         "be302461cda285db3ed2d45fb767b23e08ca8808b35a638009937df22b332d73")


if __name__ == "__main__":
    unittest.main()
