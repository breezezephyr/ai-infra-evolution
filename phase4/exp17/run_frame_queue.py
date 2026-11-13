"""Run exp17's six synthetic queue cases and write JSON to a NEW directory."""

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from frame_queue import FRAME_PERIOD_TICKS, POLICIES, SCENARIOS, TICKS_PER_SECOND, simulate


def build_experiment():
    return {
        "schema_version": "exp17.frame_queue.v1",
        "experiment": "synthetic_video_frame_queue_load",
        "synthetic_video_frames": True,
        "real_video_inference": False,
        "clock": {
            "kind": "deterministic_virtual_integer_ticks",
            "ticks_per_second": TICKS_PER_SECOND,
            "origin_ticks": 0,
            "source_frame_period_ticks": FRAME_PERIOD_TICKS,
            "all_timestamps_share_this_clock": True,
            "wall_clock_sleep": False,
            "capture_interval": "[0, duration_ms); drain after capture end",
            "equal_time_event_order": [
                "finish_running", "capture_and_apply_admission_or_replacement",
                "dequeue_and_start_if_idle", "capture_end_snapshot",
            ],
        },
        "definitions": {
            "fifo": "30 pending slots excluding running; full -> drop_new",
            "latest": "one latest pending slot; replacement -> drop_replaced; running is nonpreemptive",
            "sample_latest": "admit at >=200ms since last admitted capture, then latest; others -> drop_sampled",
            "burst": "250ms for source frame_id % 10 in [0, 1], otherwise 100ms",
            "queue_age_ticks": "dequeue - capture; null if never dequeued",
            "frame_age_ticks": "finish - capture; null if never completed",
            "pending_wait_ticks": "wait until dequeue or discard, including replaced frames",
            "cumulative_completed_wait_ticks": "sum of pending wait for completed frames after full drain",
            "cumulative_dropped_wait_ticks": "sum of pending wait for discarded frames",
            "age_summaries": "completed frames only; milliseconds; p95 uses nearest rank",
            "highwater": "max pending count, excluding running, including admission before immediate dispatch",
        },
        "limitations": [
            "Synthetic frame timestamps and prescribed service times; no real video or model inference.",
            "No hardware, visual-understanding or encoding measurements are produced.",
            "Fixed 10s capture plus full drain demonstrates queue behavior only; not model performance advice.",
            "Burst service is assigned by source frame ID; policies may complete different mixes of slow frames.",
        ],
        "runs": [simulate(policy, scenario=scenario)
                 for scenario in SCENARIOS for policy in POLICIES],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="new output directory; any existing path is refused")
    args = parser.parse_args(argv)
    serialized = json.dumps(build_experiment(), ensure_ascii=False, indent=2,
                            sort_keys=True, allow_nan=False) + "\n"
    try:
        # mkdir is the atomic no-overwrite gate, also rejecting empty directories.
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"output already exists; refusing to overwrite: {args.output}")
    except OSError as exc:
        parser.error(f"cannot create output directory: {exc}")
    result_path = args.output / "results.json"
    with result_path.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    print(f"Saved six synthetic virtual-clock queue runs: {result_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
