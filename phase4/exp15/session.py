"""Bounded, synchronous state for logical workers a/b in one event loop.

No I/O, timers, audio storage, or thread safety. Call each method without an
await in the middle; transport/authentication and ACK trust belong to server.

API:
    create(session_id, preferred_owner=None) -> session dict (sticky/idempotent)
    get(session_id) -> session dict; unknown IDs raise SessionError
    attach(session_id, owner=None) -> strictly increasing integer epoch
    disconnect(session_id, epoch) -> session dict
    begin_turn(session_id, epoch, generation, total_samples) -> session dict
    sent(session_id, epoch, generation, samples_cumulative) -> session dict
    producer_done(session_id, epoch, generation) -> session dict
    acknowledge(session_id, epoch, generation, played_samples_cumulative) -> dict
    release(session_id, epoch) -> session dict
    drain(owner) / force_drain(owner, reason) -> worker dict
    snapshot() -> {"workers": {owner: worker dict}, "sessions": {id: session dict}}

All returned dicts are detached, JSON-serializable views. Rejections raise
SessionError(code) without mutating state. Generation IDs are nonempty strings
or nonnegative integers (not bool); they cannot be reused in a session.

begin_turn on a new epoch can resume the SAME unfinished generation with the
same total. Its top-level resume_from is the played offset; mainserver resends
from there. sent/acknowledge use absolute offsets in that generation, not
bytes or counts since reconnect. sent_samples is the lifetime high-water mark;
epoch_sent_samples starts at played on reconnect and bounds fresh ACKs. The
current epoch must call begin_turn before progress updates. A producer_done
flag survives reconnect; replay does not imply a new producer.

Normal release requires producer_done, sent == total, and played == total for
the last turn. Disconnected sessions remain live and block normal drain.
force_drain is an explicit caller policy decision: total - played is recorded
as unplayed_samples, sent - played as sent_unplayed_samples; playback is never
fabricated. Released/forced IDs remain tombstones and cannot be recreated.
Retention is bounded by constructor limits; capacity rejects instead of
silently evicting disconnected sessions or deduplication/fencing evidence.
"""

from collections import deque
from dataclasses import dataclass, field


class SessionError(ValueError):
    """Stable code for server-side error mapping; exception text is the code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class _Turn:
    generation: str | int
    total_samples: int
    epoch: int
    sent_samples: int = 0
    played_samples: int = 0
    epoch_sent_samples: int = 0
    producer_done: bool = False

    @property
    def complete(self):
        return (self.producer_done and self.sent_samples == self.total_samples
                and self.played_samples == self.total_samples)


@dataclass
class _Session:
    session_id: str
    owner: str
    history: deque
    epoch: int = 0
    connected: bool = False
    status: str = "active"
    turn: _Turn | None = None
    reason: str | None = None
    generations: set = field(default_factory=set)
    sequence: int = 0


class SessionRegistry:
    def __init__(self, *, max_sessions=1024, max_generations=1024, history_limit=128):
        for limit in (max_sessions, max_generations, history_limit):
            if type(limit) is not int or limit < 1:
                raise SessionError("invalid_capacity")
        self._max_sessions = max_sessions
        self._max_generations = max_generations
        self._history_limit = history_limit
        self._sessions = {}
        self._workers = {"a": "active", "b": "active"}
        self._force_reasons = {}

    def create(self, session_id, preferred_owner=None):
        self._session_id(session_id)
        if preferred_owner is not None:
            self._owner(preferred_owner)
        existing = self._sessions.get(session_id)
        if existing is not None:
            if preferred_owner is not None and preferred_owner != existing.owner:
                raise SessionError("wrong_owner")
            if existing.status != "active":
                raise SessionError("session_closed")
            return self._view(existing)
        if preferred_owner is not None:
            if self._workers[preferred_owner] != "active":
                raise SessionError("worker_unavailable")
            owner = preferred_owner
        else:
            available = [key for key, status in self._workers.items() if status == "active"]
            if not available:
                raise SessionError("no_available_owner")
            owner = min(available, key=lambda key: sum(
                s.owner == key and s.status == "active" for s in self._sessions.values()))
        if len(self._sessions) >= self._max_sessions:
            raise SessionError("session_capacity")
        session = _Session(session_id, owner, deque(maxlen=self._history_limit))
        self._sessions[session_id] = session
        self._record(session, "create")
        return self._view(session)

    def get(self, session_id):
        return self._view(self._lookup(session_id))

    def attach(self, session_id, owner=None):
        session = self._lookup(session_id)
        if owner is not None:
            self._owner(owner)
            if owner != session.owner:
                raise SessionError("wrong_owner")
        if session.status != "active":
            raise SessionError("session_closed")
        if session.connected:
            raise SessionError("already_connected")
        session.epoch += 1
        session.connected = True
        self._record(session, "attach")
        return session.epoch

    def disconnect(self, session_id, epoch):
        session = self._connection(session_id, epoch)
        session.connected = False
        self._record(session, "disconnect")
        return self._view(session)

    def begin_turn(self, session_id, epoch, generation, total_samples):
        session = self._connection(session_id, epoch)
        if not ((type(generation) is str and generation) or
                (type(generation) is int and generation >= 0)):
            raise SessionError("invalid_generation")
        self._samples(total_samples)
        turn = session.turn
        if turn is not None and not turn.complete:
            if generation != turn.generation or epoch == turn.epoch:
                raise SessionError("generation_in_flight")
            if total_samples != turn.total_samples:
                raise SessionError("resume_mismatch")
            turn.epoch = epoch
            turn.epoch_sent_samples = turn.played_samples
            self._record(session, "resume_turn", generation=generation,
                         resume_from=turn.played_samples)
        else:
            if generation in session.generations:
                raise SessionError("duplicate_generation")
            if len(session.generations) >= self._max_generations:
                raise SessionError("generation_capacity")
            session.turn = _Turn(generation, total_samples, epoch)
            session.generations.add(generation)
            self._record(session, "begin_turn", generation=generation,
                         total_samples=total_samples)
        return self._view(session)

    def sent(self, session_id, epoch, generation, samples_cumulative):
        session, turn = self._current_turn(session_id, epoch, generation)
        self._samples(samples_cumulative)
        if not turn.epoch_sent_samples <= samples_cumulative <= turn.total_samples:
            raise SessionError("send_out_of_range")
        turn.epoch_sent_samples = samples_cumulative
        turn.sent_samples = max(turn.sent_samples, samples_cumulative)
        self._record(session, "sent", generation=generation, samples=samples_cumulative)
        return self._view(session)

    def producer_done(self, session_id, epoch, generation):
        session, turn = self._current_turn(session_id, epoch, generation)
        if turn.sent_samples != turn.total_samples or turn.epoch_sent_samples != turn.total_samples:
            raise SessionError("send_incomplete")
        turn.producer_done = True
        self._record(session, "producer_done", generation=generation)
        return self._view(session)

    def acknowledge(self, session_id, epoch, generation, played_samples_cumulative):
        session, turn = self._current_turn(session_id, epoch, generation)
        self._samples(played_samples_cumulative)
        if not turn.played_samples <= played_samples_cumulative <= turn.epoch_sent_samples:
            raise SessionError("ack_out_of_range")
        turn.played_samples = played_samples_cumulative
        self._record(session, "acknowledge", generation=generation,
                     samples=played_samples_cumulative)
        return self._view(session)

    def release(self, session_id, epoch):
        session = self._connection(session_id, epoch)
        if session.turn is not None and not session.turn.complete:
            raise SessionError("turn_incomplete")
        session.connected = False
        session.status = "released"
        session.epoch += 1
        self._record(session, "release")
        owner = session.owner
        if self._workers[owner] == "draining" and not self._live(owner):
            self._workers[owner] = "drained"
        return self._view(session)

    def drain(self, owner):
        self._owner(owner)
        if self._workers[owner] == "forced":
            raise SessionError("worker_forced")
        self._workers[owner] = "draining" if self._live(owner) else "drained"
        return self._worker_view(owner)

    def force_drain(self, owner, reason):
        self._owner(owner)
        if type(reason) is not str or not reason.strip():
            raise SessionError("invalid_reason")
        if self._workers[owner] == "forced":
            return self._worker_view(owner)
        for session in self._live(owner):
            session.connected = False
            session.status = "forced"
            session.reason = reason
            session.epoch += 1
            unplayed, delivered = self._unplayed(session)
            self._record(session, "force_drain", reason=reason,
                         unplayed_samples=unplayed, sent_unplayed_samples=delivered)
        self._workers[owner] = "forced"
        self._force_reasons[owner] = reason
        return self._worker_view(owner)

    def snapshot(self):
        return {"workers": {owner: self._worker_view(owner) for owner in self._workers},
                "sessions": {key: self._view(s) for key, s in self._sessions.items()}}

    @staticmethod
    def _session_id(session_id):
        if type(session_id) is not str or not session_id.strip():
            raise SessionError("invalid_session_id")

    def _owner(self, owner):
        if type(owner) is not str or owner not in self._workers:
            raise SessionError("unknown_owner")

    @staticmethod
    def _samples(value):
        if type(value) is not int or value < 0:
            raise SessionError("invalid_samples")

    def _lookup(self, session_id):
        self._session_id(session_id)
        if session_id not in self._sessions:
            raise SessionError("unknown_session")
        return self._sessions[session_id]

    def _connection(self, session_id, epoch):
        session = self._lookup(session_id)
        if type(epoch) is not int or epoch < 1:
            raise SessionError("invalid_epoch")
        if epoch != session.epoch:
            raise SessionError("stale_epoch")
        if session.status != "active":
            raise SessionError("session_closed")
        if not session.connected:
            raise SessionError("disconnected")
        return session

    def _current_turn(self, session_id, epoch, generation):
        session = self._connection(session_id, epoch)
        turn = session.turn
        if turn is None or type(generation) is not type(turn.generation) or generation != turn.generation:
            raise SessionError("wrong_generation")
        if turn.epoch != epoch:
            raise SessionError("turn_not_attached")
        return session, turn

    def _live(self, owner):
        return [s for s in self._sessions.values() if s.owner == owner and s.status == "active"]

    @staticmethod
    def _record(session, event, **details):
        session.sequence += 1
        session.history.append({"sequence": session.sequence, "event": event,
                                "epoch": session.epoch, "owner": session.owner, **details})

    @staticmethod
    def _unplayed(session):
        turn = session.turn
        if turn is None:
            return 0, 0
        return turn.total_samples - turn.played_samples, turn.sent_samples - turn.played_samples

    def _view(self, session):
        turn = session.turn
        unplayed, delivered = self._unplayed(session)
        return {"session_id": session.session_id, "owner": session.owner,
                "epoch": session.epoch, "connected": session.connected,
                "status": session.status, "reason": session.reason,
                "resume_from": turn.played_samples if turn else 0,
                "unplayed_samples": unplayed, "sent_unplayed_samples": delivered,
                "turn": vars(turn).copy() if turn else None,
                "history": [event.copy() for event in session.history]}

    def _worker_view(self, owner):
        live = self._live(owner)
        return {"owner": owner, "status": self._workers[owner],
                "active_sessions": len(live), "session_ids": [s.session_id for s in live],
                "drained": self._workers[owner] == "drained",
                "reason": self._force_reasons.get(owner),
                "unplayed_samples": sum(self._unplayed(s)[0] for s in self._sessions.values()
                                        if s.owner == owner and s.status == "forced")}
