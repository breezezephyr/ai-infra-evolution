"""Synthetic video-frame queues; deterministic virtual time, no video or inference.

One tick is 1/3000 second: 30fps = 100 ticks, 1ms = 3 ticks, all exact.
At a tie: finish running -> capture/replace pending -> dequeue/start -> end snapshot.
Capacity counts pending frames only. Running work is never preempted.
"""

from collections import deque

TICKS_PER_SECOND = 3000
TICKS_PER_MS = 3
FRAME_PERIOD_TICKS = 100
POLICIES = ("fifo", "latest", "sample_latest")
SCENARIOS = ("fixed", "burst")


def _age_summary(values):
    """Completed-frame ages only; p95 uses the nearest-rank convention."""
    if not values:
        return {"mean_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {
        "mean_ms": sum(values) / (len(values) * TICKS_PER_MS),
        "p95_ms": ordered[(95 * len(values) + 99) // 100 - 1] / TICKS_PER_MS,
        "max_ms": ordered[-1] / TICKS_PER_MS,
    }


def simulate(policy, *, scenario="fixed", duration_ms=10000, capacity=30,
             sample_interval_ms=200, service_ms=100, slow_service_ms=250):
    """Capture in [0, duration), then drain a single virtual worker completely.

    burst assigns slow service to source frame_id % 10 in (0, 1), including frames
    later discarded. sample_latest gates against the last admitted capture time;
    rejected captures do not reset that gate. Discarded frames have no dequeue,
    start, finish, queue_age or completion frame_age; pending_wait still records
    their time until discard. No wall clock, sleeps, GPU or model measurements.
    """
    if policy not in POLICIES or scenario not in SCENARIOS:
        raise ValueError("unknown policy or scenario")
    for name, value, minimum in [
        ("duration_ms", duration_ms, 0), ("capacity", capacity, 1),
        ("sample_interval_ms", sample_interval_ms, 1),
        ("service_ms", service_ms, 1), ("slow_service_ms", slow_service_ms, 1),
    ]:
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")

    capture_end = duration_ms * TICKS_PER_MS
    sample_interval = sample_interval_ms * TICKS_PER_MS
    pending_capacity = capacity if policy == "fifo" else 1
    pending = deque()
    frames = []
    events = []
    running = None
    running_finish = None
    now = 0
    next_capture = 0
    capture_closed = False
    last_admitted_capture = None
    capture_end_state = None
    completed_count = 0
    admitted_count = 0
    highwater = 0
    dequeued_wait = 0
    dropped_wait = 0
    drop_counts = {"drop_new": 0, "drop_replaced": 0, "drop_sampled": 0}

    def emit(event, frame=None):
        events.append({
            "ticks": now,
            "event": event,
            "frame_id": None if frame is None else frame["frame_id"],
            "pending_count": len(pending),
            "running_frame_id": None if running is None else running["frame_id"],
            "completed_count": completed_count,
            "drop_count": sum(drop_counts.values()),
            "cumulative_dequeued_wait_ticks": dequeued_wait,
            "cumulative_dropped_wait_ticks": dropped_wait,
        })

    def discard(frame, reason):
        nonlocal dropped_wait
        frame["status"] = "dropped"
        frame["drop_reason"] = reason
        frame["drop_ticks"] = now
        frame["pending_wait_ticks"] = now - frame["capture_ticks"]
        dropped_wait += frame["pending_wait_ticks"]
        drop_counts[reason] += 1
        emit(reason, frame)

    while not capture_closed or running is not None or pending:
        candidates = []
        if not capture_closed:
            candidates.append(capture_end)
        if next_capture < capture_end:
            candidates.append(next_capture)
        if running is not None:
            candidates.append(running_finish)
        now = min(candidates)

        if running is not None and running_finish == now:
            finished = running
            finished["finish_ticks"] = now
            finished["frame_age_ticks"] = now - finished["capture_ticks"]
            finished["status"] = "completed"
            completed_count += 1
            running = None
            running_finish = None
            emit("finish", finished)

        if next_capture < capture_end and next_capture == now:
            frame_id = len(frames)
            is_slow = scenario == "burst" and frame_id % 10 in (0, 1)
            frame = {
                "frame_id": frame_id,
                "frame_timestamp_ticks": now,
                "capture_ticks": now,
                "dequeue_ticks": None,
                "start_ticks": None,
                "finish_ticks": None,
                "queue_age_ticks": None,
                "frame_age_ticks": None,
                "pending_wait_ticks": 0,
                "service_ticks": (slow_service_ms if is_slow else service_ms) * TICKS_PER_MS,
                "admitted": False,
                "status": "captured",
                "drop_reason": None,
                "drop_ticks": None,
            }
            frames.append(frame)
            next_capture += FRAME_PERIOD_TICKS
            emit("capture", frame)
            if (policy == "sample_latest" and last_admitted_capture is not None
                    and now - last_admitted_capture < sample_interval):
                discard(frame, "drop_sampled")
            elif policy == "fifo" and len(pending) == pending_capacity:
                discard(frame, "drop_new")
            else:
                if policy != "fifo" and pending:
                    discard(pending.pop(), "drop_replaced")
                pending.append(frame)
                frame["admitted"] = True
                frame["status"] = "pending"
                admitted_count += 1
                last_admitted_capture = now
                highwater = max(highwater, len(pending))
                emit("admit", frame)

        # Dispatch only after all captures at this tick have applied replacement.
        if running is None and pending:
            frame = pending.popleft()
            frame["dequeue_ticks"] = now
            frame["queue_age_ticks"] = now - frame["capture_ticks"]
            frame["pending_wait_ticks"] = frame["queue_age_ticks"]
            dequeued_wait += frame["queue_age_ticks"]
            emit("dequeue", frame)
            running = frame
            running["status"] = "running"
            running["start_ticks"] = now
            running_finish = now + running["service_ticks"]
            emit("start", running)

        if not capture_closed and now == capture_end:
            capture_closed = True
            emit("capture_end")
            capture_end_state = events[-1].copy()

    completed = [frame for frame in frames if frame["status"] == "completed"]
    last_finish = max((frame["finish_ticks"] for frame in completed), default=None)
    emit("drained")
    return {
        "policy": policy,
        "scenario": scenario,
        "config": {
            "source_fps": 30,
            "duration_ms": duration_ms,
            "pending_capacity": pending_capacity,
            "capacity_excludes_running": True,
            "sample_interval_ms": sample_interval_ms if policy == "sample_latest" else None,
            "service_ms": service_ms,
            "slow_service_ms": slow_service_ms if scenario == "burst" else None,
            "slow_source_frame_id_mod_10": [0, 1] if scenario == "burst" else [],
        },
        "capture_end_ticks": capture_end,
        "capture_end_state": capture_end_state,
        "frames": frames,
        "events": events,
        "metrics": {
            "source_count": len(frames),
            "admitted_count": admitted_count,
            "completed_count": completed_count,
            "drop_count": sum(drop_counts.values()),
            "drop_counts": drop_counts,
            "pending_highwater": highwater,
            "completed_by_capture_end_count": capture_end_state["completed_count"],
            "completed_after_capture_end_count": completed_count - capture_end_state["completed_count"],
            "cumulative_completed_wait_ticks": dequeued_wait,
            "cumulative_dropped_wait_ticks": dropped_wait,
            "cumulative_wait_ticks": dequeued_wait + dropped_wait,
            "queue_age_completed": _age_summary([f["queue_age_ticks"] for f in completed]),
            "frame_age_completed": _age_summary([f["frame_age_ticks"] for f in completed]),
            "last_finish_ticks": last_finish,
            "simulation_end_ticks": now,
            "drain_ticks": now - capture_end,
            "final_pending_count": len(pending),
            "final_running_frame_id": None if running is None else running["frame_id"],
        },
    }
