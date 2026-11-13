"""Behavior tests for synthetic frames on a single deterministic virtual clock."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True


class FrameQueueTests(unittest.TestCase):
    def simulate(self, policy, **kwargs):
        try:
            from frame_queue import simulate
        except ModuleNotFoundError as exc:
            if exc.name != "frame_queue":
                raise
            self.fail("frame_queue.simulate has not been implemented")
        return simulate(policy, **kwargs)

    @staticmethod
    def completed_ids(result):
        return [f["frame_id"] for f in result["frames"] if f["status"] == "completed"]

    def test_fifo_drops_new_at_capacity_and_preserves_old_pending(self):
        result = self.simulate("fifo", duration_ms=200, capacity=2)
        self.assertEqual(self.completed_ids(result), [0, 1, 2, 4])
        self.assertEqual(result["metrics"]["pending_highwater"], 2)
        self.assertEqual(result["metrics"]["drop_counts"],
                         {"drop_new": 2, "drop_replaced": 0, "drop_sampled": 0})
        for frame_id, drop_tick in [(3, 300), (5, 500)]:
            frame = result["frames"][frame_id]
            self.assertEqual(frame["drop_reason"], "drop_new")
            self.assertEqual(frame["drop_ticks"], drop_tick)
            self.assertEqual(frame["pending_wait_ticks"], 0)
            self.assertIsNone(frame["start_ticks"])

    def test_default_fifo_capacity_is_30_waiting_frames_excluding_running(self):
        result = self.simulate("fifo")
        self.assertEqual(result["metrics"]["pending_highwater"], 30)
        self.assertEqual(result["metrics"]["completed_count"], 130)
        self.assertEqual(result["metrics"]["drop_counts"]["drop_new"], 170)
        self.assertEqual(result["metrics"]["drain_ticks"], 9000)

    def test_latest_replaces_pending_without_preempting_running(self):
        result = self.simulate("latest", duration_ms=200, service_ms=250)
        self.assertEqual(self.completed_ids(result), [0, 5])
        self.assertEqual(result["frames"][0]["start_ticks"], 0)
        self.assertEqual(result["frames"][0]["finish_ticks"], 750)
        self.assertEqual(result["frames"][5]["start_ticks"], 750)
        self.assertEqual(result["frames"][5]["finish_ticks"], 1500)
        for frame_id in [1, 2, 3, 4]:
            self.assertEqual(result["frames"][frame_id]["drop_reason"], "drop_replaced")
            self.assertIsNone(result["frames"][frame_id]["dequeue_ticks"])
        self.assertEqual(result["metrics"]["pending_highwater"], 1)

    def test_coincident_finish_and_capture_dispatches_the_newest_frame(self):
        result = self.simulate("latest", duration_ms=200)
        self.assertEqual(self.completed_ids(result), [0, 3, 5])
        self.assertEqual(result["frames"][2]["drop_ticks"], 300)
        self.assertEqual(result["frames"][3]["dequeue_ticks"], 300)
        self.assertEqual(result["frames"][3]["start_ticks"], 300)

    def test_sample_gate_accepts_exact_200ms_and_rejections_do_not_reset_it(self):
        result = self.simulate("sample_latest", duration_ms=500)
        self.assertEqual(self.completed_ids(result), [0, 6, 12])
        self.assertEqual(result["metrics"]["admitted_count"], 3)
        self.assertEqual(result["metrics"]["drop_counts"]["drop_sampled"], 12)
        self.assertEqual(result["frames"][6]["capture_ticks"], 600)
        self.assertEqual(result["frames"][12]["capture_ticks"], 1200)
        self.assertEqual(result["metrics"]["drain_ticks"], 0)

    def test_sampling_is_a_time_gate_rather_than_every_nth_frame(self):
        result = self.simulate("sample_latest", duration_ms=500, sample_interval_ms=201)
        self.assertEqual(self.completed_ids(result), [0, 7, 14])

    def test_sample_latest_can_replace_pending_but_cannot_preempt_running(self):
        result = self.simulate("sample_latest", duration_ms=1000, service_ms=500)
        self.assertEqual(self.completed_ids(result), [0, 12, 24])
        self.assertEqual(result["metrics"]["drop_counts"],
                         {"drop_new": 0, "drop_replaced": 2, "drop_sampled": 25})
        self.assertEqual(result["frames"][0]["finish_ticks"], 1500)
        self.assertEqual(result["frames"][6]["drop_ticks"], 1200)
        self.assertEqual(result["frames"][18]["drop_ticks"], 2400)

    def test_capture_end_is_exclusive_and_tail_is_fully_drained(self):
        result = self.simulate("fifo", duration_ms=200)
        self.assertEqual([f["capture_ticks"] for f in result["frames"]],
                         [0, 100, 200, 300, 400, 500])
        self.assertEqual(result["capture_end_ticks"], 600)
        self.assertEqual(result["metrics"]["last_finish_ticks"], 1800)
        self.assertEqual(result["metrics"]["simulation_end_ticks"], 1800)
        self.assertEqual(result["metrics"]["drain_ticks"], 1200)
        self.assertEqual(result["metrics"]["completed_by_capture_end_count"], 2)
        self.assertEqual(result["metrics"]["final_pending_count"], 0)
        self.assertIsNone(result["metrics"]["final_running_frame_id"])

    def test_sub_frame_duration_empty_source_and_exact_boundary(self):
        for duration, ids in [(0, []), (1, [0]), (100, [0, 1, 2]), (101, [0, 1, 2, 3])]:
            with self.subTest(duration_ms=duration):
                result = self.simulate("latest", duration_ms=duration)
                self.assertEqual([f["frame_id"] for f in result["frames"]], ids)
                self.assertGreaterEqual(result["metrics"]["simulation_end_ticks"], duration * 3)
        empty = self.simulate("fifo", duration_ms=0)
        self.assertIsNone(empty["metrics"]["last_finish_ticks"])
        self.assertEqual(empty["metrics"]["cumulative_wait_ticks"], 0)

    def test_waiting_and_frame_age_use_the_same_clock_and_include_replaced_wait(self):
        result = self.simulate("latest", duration_ms=200)
        last = result["frames"][5]
        self.assertEqual(last["queue_age_ticks"], 100)
        self.assertEqual(last["pending_wait_ticks"], 100)
        self.assertEqual(last["frame_age_ticks"], 400)
        self.assertEqual(result["metrics"]["cumulative_completed_wait_ticks"], 100)
        self.assertEqual(result["metrics"]["cumulative_dropped_wait_ticks"], 300)
        self.assertEqual(result["metrics"]["cumulative_wait_ticks"], 400)
        fifo = self.simulate("fifo", duration_ms=200)
        self.assertEqual(fifo["metrics"]["cumulative_completed_wait_ticks"], 3000)
        self.assertEqual(fifo["metrics"]["cumulative_dropped_wait_ticks"], 0)

    def test_burst_service_is_assigned_by_source_frame_id(self):
        result = self.simulate("latest", scenario="burst", duration_ms=334)
        self.assertEqual(self.completed_ids(result), [0, 7, 10])
        self.assertEqual([result["frames"][i]["service_ticks"] for i in [0, 7, 10]],
                         [750, 300, 750])
        self.assertEqual(result["frames"][10]["finish_ticks"], 1800)
        fifo = self.simulate("fifo", scenario="burst", duration_ms=1000)
        self.assertEqual(fifo["metrics"]["completed_count"], 30)
        self.assertEqual(fifo["metrics"]["last_finish_ticks"], 11700)

    def test_all_six_runs_conserve_source_frames_and_have_consistent_timelines(self):
        for scenario in ["fixed", "burst"]:
            for policy in ["fifo", "latest", "sample_latest"]:
                with self.subTest(scenario=scenario, policy=policy):
                    result = self.simulate(policy, scenario=scenario)
                    metrics = result["metrics"]
                    self.assertEqual(len(result["frames"]), 300)
                    self.assertEqual(metrics["source_count"], 300)
                    self.assertEqual(metrics["completed_count"] + metrics["drop_count"], 300)
                    self.assertEqual(sum(metrics["drop_counts"].values()), metrics["drop_count"])
                    self.assertEqual(metrics["admitted_count"],
                                     metrics["completed_count"] + metrics["drop_counts"]["drop_replaced"])
                    self.assertEqual(metrics["cumulative_wait_ticks"],
                                     sum(f["pending_wait_ticks"] for f in result["frames"]))
                    completed = [f for f in result["frames"] if f["status"] == "completed"]
                    previous_finish = 0
                    for frame in result["frames"]:
                        self.assertEqual(frame["capture_ticks"], frame["frame_id"] * 100)
                        self.assertEqual(frame["frame_timestamp_ticks"], frame["capture_ticks"])
                        if frame["status"] == "completed":
                            self.assertEqual(frame["dequeue_ticks"], frame["start_ticks"])
                            self.assertGreaterEqual(frame["start_ticks"], frame["capture_ticks"])
                            self.assertGreaterEqual(frame["start_ticks"], previous_finish)
                            self.assertEqual(frame["finish_ticks"] - frame["start_ticks"],
                                             frame["service_ticks"])
                            self.assertEqual(frame["queue_age_ticks"],
                                             frame["start_ticks"] - frame["capture_ticks"])
                            self.assertEqual(frame["frame_age_ticks"],
                                             frame["finish_ticks"] - frame["capture_ticks"])
                            self.assertIsNone(frame["drop_reason"])
                            self.assertIsNone(frame["drop_ticks"])
                            previous_finish = frame["finish_ticks"]
                        else:
                            self.assertEqual(frame["status"], "dropped")
                            self.assertGreaterEqual(frame["drop_ticks"], frame["capture_ticks"])
                            self.assertEqual(frame["pending_wait_ticks"],
                                             frame["drop_ticks"] - frame["capture_ticks"])
                            for field in ["dequeue_ticks", "start_ticks", "finish_ticks",
                                          "queue_age_ticks", "frame_age_ticks"]:
                                self.assertIsNone(frame[field])
                    self.assertEqual(metrics["completed_count"], len(completed))
                    self.assertEqual(metrics["final_pending_count"], 0)
                    self.assertIsNone(metrics["final_running_frame_id"])

    def test_repeated_runs_are_deterministic(self):
        self.assertEqual(self.simulate("latest", scenario="burst"),
                         self.simulate("latest", scenario="burst"))

    def test_invalid_inputs_fail_before_simulation(self):
        for kwargs in [{"policy": "unknown"}, {"scenario": "unknown"},
                       {"duration_ms": -1}, {"duration_ms": 1.5},
                       {"capacity": 0}, {"service_ms": 0},
                       {"slow_service_ms": -1}, {"sample_interval_ms": 0}]:
            with self.subTest(kwargs=kwargs):
                config = {"policy": "fifo", **kwargs}
                with self.assertRaises(ValueError):
                    self.simulate(**config)


class RunnerTests(unittest.TestCase):
    script = Path(__file__).with_name("run_frame_queue.py")

    def run_cli(self, output, cwd):
        return subprocess.run(
            [sys.executable, "-B", str(self.script), "--output", str(output)],
            cwd=cwd, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )

    def test_cli_writes_six_synthetic_runs_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fresh"
            first = self.run_cli(output, temp_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            result_path = output / "results.json"
            original = result_path.read_bytes()
            payload = json.loads(original)
            self.assertTrue(payload["synthetic_video_frames"])
            self.assertFalse(payload["real_video_inference"])
            self.assertEqual(payload["clock"]["ticks_per_second"], 3000)
            self.assertEqual(len(payload["runs"]), 6)
            self.assertEqual({(r["scenario"], r["policy"]) for r in payload["runs"]},
                             {(s, p) for s in ["fixed", "burst"]
                              for p in ["fifo", "latest", "sample_latest"]})
            for run in payload["runs"]:
                self.assertEqual(run["capture_end_ticks"], 30000)
                self.assertEqual(run["metrics"]["source_count"], 300)
            forbidden = {"gpu_utilization", "gpu_memory_mb", "visual_understanding_quality",
                         "encoding_latency_ms"}
            def check_keys(value):
                if isinstance(value, dict):
                    self.assertTrue(forbidden.isdisjoint(value))
                    for child in value.values():
                        check_keys(child)
                elif isinstance(value, list):
                    for child in value:
                        check_keys(child)
            check_keys(payload)
            second = self.run_cli(output, temp_dir)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(result_path.read_bytes(), original)
            other = Path(temp_dir) / "another-fresh"
            self.assertEqual(self.run_cli(other, temp_dir).returncode, 0)
            self.assertEqual((other / "results.json").read_bytes(), original)

    def test_cli_also_refuses_existing_empty_directory_and_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "empty"
            existing.mkdir()
            directory_run = self.run_cli(existing, temp_dir)
            self.assertNotEqual(directory_run.returncode, 0)
            self.assertIn("refusing to overwrite", directory_run.stderr)
            self.assertEqual(list(existing.iterdir()), [])
            file_target = Path(temp_dir) / "keep.txt"
            file_target.write_text("keep", encoding="utf-8")
            file_run = self.run_cli(file_target, temp_dir)
            self.assertNotEqual(file_run.returncode, 0)
            self.assertIn("refusing to overwrite", file_run.stderr)
            self.assertEqual(file_target.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
