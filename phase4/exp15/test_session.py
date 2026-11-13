"""Functional state-machine tests; no network, clocks, sleeps, or mocks."""

import json
import unittest

from session import SessionError, SessionRegistry


class SessionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = SessionRegistry()

    def assert_rejected(self, code, operation, *args):
        before = self.registry.snapshot()
        with self.assertRaises(SessionError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.registry.snapshot(), before, "rejection mutated state")

    def connect(self, session_id="s", owner="a"):
        self.registry.create(session_id, owner)
        return self.registry.attach(session_id, owner)

    def test_owner_is_sticky_and_draining_routes_new_sessions_elsewhere(self):
        self.assertEqual(self.registry.create("s", "a")["owner"], "a")
        self.assert_rejected("wrong_owner", self.registry.create, "s", "b")
        self.assert_rejected("wrong_owner", self.registry.attach, "s", "b")
        self.assertEqual(self.registry.drain("a")["status"], "draining")
        self.assertEqual(self.registry.create("s")["owner"], "a")
        self.assertEqual(self.registry.attach("s", "a"), 1)
        self.assert_rejected("worker_unavailable", self.registry.create, "new-a", "a")
        self.assertEqual(self.registry.create("new")["owner"], "b")
        self.registry.drain("b")
        self.assert_rejected("no_available_owner", self.registry.create, "blocked")

    def test_reconnect_preserves_progress_and_fences_every_old_connection_control(self):
        first = self.connect()
        self.assert_rejected("already_connected", self.registry.attach, "s", "a")
        self.registry.begin_turn("s", first, "g1", 100)
        self.registry.sent("s", first, "g1", 80)
        self.registry.acknowledge("s", first, "g1", 30)
        self.registry.disconnect("s", first)
        self.assertEqual(self.registry.get("s")["turn"]["played_samples"], 30)
        self.assert_rejected("disconnected", self.registry.acknowledge, "s", first, "g1", 40)
        second = self.registry.attach("s", "a")
        self.assertGreater(second, first)
        for operation, tail in (
            (self.registry.disconnect, ()),
            (self.registry.begin_turn, ("g1", 100)),
            (self.registry.sent, ("g1", 90)),
            (self.registry.producer_done, ("g1",)),
            (self.registry.acknowledge, ("g1", 40)),
            (self.registry.release, ()),
        ):
            with self.subTest(operation=operation.__name__):
                self.assert_rejected("stale_epoch", operation, "s", first, *tail)
        self.assert_rejected("turn_not_attached", self.registry.acknowledge, "s", second, "g1", 40)
        resumed = self.registry.begin_turn("s", second, "g1", 100)
        self.assertEqual(resumed["resume_from"], 30)
        self.assertEqual(resumed["turn"]["sent_samples"], 80)
        self.assert_rejected("ack_out_of_range", self.registry.acknowledge, "s", second, "g1", 40)
        self.registry.sent("s", second, "g1", 50)
        self.registry.acknowledge("s", second, "g1", 50)
        self.assertEqual(self.registry.get("s")["turn"]["sent_samples"], 80)
        self.registry.sent("s", second, "g1", 100)
        self.registry.producer_done("s", second, "g1")
        self.registry.acknowledge("s", second, "g1", 100)
        self.assertEqual(self.registry.release("s", second)["status"], "released")

    def test_only_one_generation_and_completed_ids_cannot_be_reused(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, 1, 10)
        self.assert_rejected("generation_in_flight", self.registry.begin_turn, "s", epoch, 1, 10)
        self.assert_rejected("generation_in_flight", self.registry.begin_turn, "s", epoch, 2, 10)
        self.assert_rejected("wrong_generation", self.registry.sent, "s", epoch, 2, 10)
        self.assert_rejected("wrong_generation", self.registry.acknowledge, "s", epoch, 2, 0)
        self.assert_rejected("wrong_generation", self.registry.producer_done, "s", epoch, 2)
        self.registry.sent("s", epoch, 1, 10)
        self.registry.acknowledge("s", epoch, 1, 10)
        self.assert_rejected("generation_in_flight", self.registry.begin_turn, "s", epoch, 2, 10)
        self.registry.producer_done("s", epoch, 1)
        self.assert_rejected("duplicate_generation", self.registry.begin_turn, "s", epoch, 1, 10)
        self.registry.begin_turn("s", epoch, 2, 5)
        self.registry.sent("s", epoch, 2, 5)
        self.registry.producer_done("s", epoch, 2)
        self.registry.acknowledge("s", epoch, 2, 5)
        self.assert_rejected("duplicate_generation", self.registry.begin_turn, "s", epoch, 1, 10)
        self.assertEqual(self.registry.get("s")["turn"]["generation"], 2)

    def test_cumulative_send_and_ack_bounds_reject_without_mutation(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 100)
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                self.assert_rejected("invalid_samples", self.registry.sent, "s", epoch, "g", value)
                self.assert_rejected("invalid_samples", self.registry.acknowledge, "s", epoch, "g", value)
        self.assert_rejected("send_out_of_range", self.registry.sent, "s", epoch, "g", 101)
        self.assert_rejected("ack_out_of_range", self.registry.acknowledge, "s", epoch, "g", 1)
        self.registry.sent("s", epoch, "g", 60)
        self.registry.acknowledge("s", epoch, "g", 40)
        self.assert_rejected("send_out_of_range", self.registry.sent, "s", epoch, "g", 59)
        self.assert_rejected("ack_out_of_range", self.registry.acknowledge, "s", epoch, "g", 39)
        self.assert_rejected("ack_out_of_range", self.registry.acknowledge, "s", epoch, "g", 61)
        self.registry.sent("s", epoch, "g", 60)
        self.registry.acknowledge("s", epoch, "g", 40)
        self.assertEqual(self.registry.get("s")["unplayed_samples"], 60)

    def test_normal_drain_waits_for_producer_playback_and_explicit_release(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 100)
        self.registry.drain("a")
        self.assert_rejected("send_incomplete", self.registry.producer_done, "s", epoch, "g")
        self.assert_rejected("turn_incomplete", self.registry.release, "s", epoch)
        self.registry.sent("s", epoch, "g", 100)
        self.registry.acknowledge("s", epoch, "g", 100)
        self.assert_rejected("turn_incomplete", self.registry.release, "s", epoch)
        self.registry.producer_done("s", epoch, "g")
        self.assertEqual(self.registry.snapshot()["workers"]["a"]["status"], "draining")
        self.registry.begin_turn("s", epoch, "next", 20)
        self.registry.sent("s", epoch, "next", 20)
        self.registry.producer_done("s", epoch, "next")
        self.assert_rejected("turn_incomplete", self.registry.release, "s", epoch)
        self.assertEqual(self.registry.get("s")["turn"]["played_samples"], 0)
        self.registry.acknowledge("s", epoch, "next", 20)
        self.assertEqual(self.registry.snapshot()["workers"]["a"]["active_sessions"], 1)
        self.registry.release("s", epoch)
        self.assertEqual(self.registry.snapshot()["workers"]["a"]["status"], "drained")
        self.assert_rejected("session_closed", self.registry.attach, "s", "a")
        self.assert_rejected("session_closed", self.registry.create, "s", "a")
        self.assert_rejected("stale_epoch", self.registry.acknowledge, "s", epoch, "next", 20)

    def test_disconnected_session_keeps_drain_pending_until_replay_is_acknowledged(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 100)
        self.registry.sent("s", epoch, "g", 100)
        self.registry.producer_done("s", epoch, "g")
        self.registry.acknowledge("s", epoch, "g", 25)
        self.registry.disconnect("s", epoch)
        self.assertEqual(self.registry.drain("a")["status"], "draining")
        new_epoch = self.registry.attach("s", "a")
        self.assert_rejected("resume_mismatch", self.registry.begin_turn, "s", new_epoch, "g", 101)
        self.assert_rejected("generation_in_flight", self.registry.begin_turn, "s", new_epoch, "other", 100)
        resumed = self.registry.begin_turn("s", new_epoch, "g", 100)
        self.assertEqual(resumed["resume_from"], 25)
        self.assertTrue(resumed["turn"]["producer_done"])
        self.assert_rejected("send_incomplete", self.registry.producer_done, "s", new_epoch, "g")
        self.registry.sent("s", new_epoch, "g", 100)
        self.assert_rejected("turn_incomplete", self.registry.release, "s", new_epoch)
        self.registry.acknowledge("s", new_epoch, "g", 100)
        self.registry.release("s", new_epoch)
        self.assertEqual(self.registry.snapshot()["workers"]["a"]["status"], "drained")

    def test_force_drain_records_loss_and_invalidates_connected_and_disconnected_epochs(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 100)
        self.registry.sent("s", epoch, "g", 80)
        self.registry.acknowledge("s", epoch, "g", 30)
        finished_epoch = self.connect("finished")
        finished = self.registry.release("finished", finished_epoch)
        offline_epoch = self.connect("offline")
        self.registry.begin_turn("offline", offline_epoch, "h", 20)
        self.registry.disconnect("offline", offline_epoch)
        other_epoch = self.connect("other", "b")
        self.registry.drain("a")
        forced = self.registry.force_drain("a", "deadline_by_caller")
        self.assertEqual(forced["status"], "forced")
        self.assertFalse(forced["drained"])
        self.assertEqual(forced["active_sessions"], 0)
        self.assertEqual(forced["unplayed_samples"], 90)
        state = self.registry.get("s")
        self.assertEqual((state["status"], state["reason"]), ("forced", "deadline_by_caller"))
        self.assertEqual((state["unplayed_samples"], state["sent_unplayed_samples"]), (70, 50))
        self.assertEqual(state["turn"]["played_samples"], 30)
        self.assertFalse(state["turn"]["producer_done"])
        self.assertGreater(state["epoch"], epoch)
        for operation, tail in (
            (self.registry.disconnect, ()),
            (self.registry.begin_turn, ("g", 100)),
            (self.registry.sent, ("g", 100)),
            (self.registry.producer_done, ("g",)),
            (self.registry.acknowledge, ("g", 80)),
            (self.registry.release, ()),
        ):
            with self.subTest(operation=operation.__name__):
                self.assert_rejected("stale_epoch", operation, "s", epoch, *tail)
        self.assert_rejected("stale_epoch", self.registry.acknowledge, "offline", offline_epoch, "h", 0)
        self.assert_rejected("session_closed", self.registry.attach, "s", "a")
        self.assertEqual(self.registry.get("other")["epoch"], other_epoch)
        self.assertTrue(self.registry.get("other")["connected"])
        self.assertEqual(self.registry.get("finished"), finished)
        self.assertEqual(self.registry.force_drain("a", "ignored_retry"), forced)

    def test_drain_waits_for_every_session_including_disconnected_idle_sessions(self):
        first = self.connect("first")
        second = self.connect("second")
        other = self.connect("other", "b")
        self.registry.disconnect("second", second)
        self.assertEqual(self.registry.drain("a")["active_sessions"], 2)
        self.registry.release("first", first)
        pending = self.registry.snapshot()["workers"]["a"]
        self.assertEqual((pending["status"], pending["active_sessions"]), ("draining", 1))
        resumed = self.registry.attach("second", "a")
        self.registry.release("second", resumed)
        workers = self.registry.snapshot()["workers"]
        self.assertEqual(workers["a"]["status"], "drained")
        self.assertEqual(workers["b"]["status"], "active")
        self.assertEqual(self.registry.get("other")["epoch"], other)

    def test_empty_and_zero_audio_sessions_can_release_and_idle_workers_drain(self):
        epoch = self.connect()
        self.registry.release("s", epoch)
        epoch = self.connect("silent")
        self.registry.begin_turn("silent", epoch, "silence", 0)
        self.assert_rejected("turn_incomplete", self.registry.release, "silent", epoch)
        self.registry.producer_done("silent", epoch, "silence")
        self.registry.release("silent", epoch)
        self.assertEqual(self.registry.drain("a")["status"], "drained")
        self.assertEqual(self.registry.drain("b")["status"], "drained")

    def test_caller_cannot_mutate_read_results_or_event_history(self):
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 10)
        state = self.registry.get("s")
        state["owner"] = "b"
        state["turn"]["played_samples"] = 10
        state["history"][0]["event"] = "forged"
        snapshot = self.registry.snapshot()
        snapshot["workers"]["a"]["status"] = "drained"
        snapshot["sessions"].clear()
        current = self.registry.get("s")
        self.assertEqual(current["owner"], "a")
        self.assertEqual(current["turn"]["played_samples"], 0)
        self.assertEqual([item["event"] for item in current["history"]], ["create", "attach", "begin_turn"])
        self.assertEqual(self.registry.snapshot()["workers"]["a"]["status"], "active")
        decoded = json.loads(json.dumps(self.registry.snapshot()))
        self.assertEqual(decoded["sessions"]["s"]["turn"]["generation"], "g")

    def test_retained_state_has_explicit_bounds_without_eviction_or_clock(self):
        self.registry = SessionRegistry(max_sessions=1, max_generations=1, history_limit=3)
        epoch = self.connect()
        self.registry.begin_turn("s", epoch, "g", 1)
        self.registry.sent("s", epoch, "g", 1)
        self.registry.producer_done("s", epoch, "g")
        self.registry.acknowledge("s", epoch, "g", 1)
        self.assert_rejected("generation_capacity", self.registry.begin_turn, "s", epoch, "next", 1)
        self.assertEqual(len(self.registry.get("s")["history"]), 3)
        self.registry.release("s", epoch)
        self.assert_rejected("session_capacity", self.registry.create, "new")
        self.assertEqual(self.registry.get("s")["status"], "released")

    def test_invalid_identity_and_numeric_inputs_do_not_consume_state(self):
        self.assert_rejected("unknown_session", self.registry.get, "missing")
        self.assert_rejected("invalid_session_id", self.registry.create, "")
        self.assert_rejected("unknown_owner", self.registry.create, "s", "c")
        self.assert_rejected("unknown_owner", self.registry.drain, "c")
        epoch = self.connect()
        self.assert_rejected("invalid_epoch", self.registry.disconnect, "s", True)
        self.assert_rejected("invalid_generation", self.registry.begin_turn, "s", epoch, "", 1)
        self.assert_rejected("invalid_samples", self.registry.begin_turn, "s", epoch, "g", -1)
        self.assert_rejected("invalid_reason", self.registry.force_drain, "a", "")
        self.assertIsNone(self.registry.get("s")["turn"])


if __name__ == "__main__":
    unittest.main()
