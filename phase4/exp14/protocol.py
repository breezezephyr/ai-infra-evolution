"""Bounded PCM16LE packets and stream validation for exp14.

Each packet has a 28-byte little-endian ``<4sIIIQI`` header followed by
1..3200 PCM16 samples. The last header field counts samples, not bytes.
Sample rates and session identity belong to the surrounding control protocol.
Malformed values and protocol violations raise ValueError; non-bytes audio
arguments raise TypeError.
"""

import struct
from dataclasses import dataclass


MAGIC = b"P4A1"
HEADER = struct.Struct("<4sIIIQI")
MAX_SAMPLES = 3200


@dataclass(frozen=True)
class AudioFrame:
    turn_id: int
    generation_id: int
    seq: int
    sample_offset: int
    pcm: bytes


def _uint(value: int, bits: int, name: str) -> None:
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")


def _require_bytes(value: bytes, name: str) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{name} must be bytes")


def _pcm_samples(pcm: bytes) -> int:
    _require_bytes(pcm, "pcm")
    if not pcm or len(pcm) % 2:
        raise ValueError("pcm must contain nonempty, complete PCM16 samples")
    samples = len(pcm) // 2
    if samples > MAX_SAMPLES:
        raise ValueError(f"audio packet exceeds {MAX_SAMPLES} samples")
    return samples


def pack_audio(
    turn_id: int, generation_id: int, seq: int, sample_offset: int, pcm: bytes
) -> bytes:
    """Encode one packet; IDs/seq are uint32 and sample_offset is uint64."""
    _uint(turn_id, 32, "turn_id")
    _uint(generation_id, 32, "generation_id")
    _uint(seq, 32, "seq")
    _uint(sample_offset, 64, "sample_offset")
    samples = _pcm_samples(pcm)
    return HEADER.pack(MAGIC, turn_id, generation_id, seq, sample_offset, samples) + pcm


def unpack_audio(data: bytes) -> AudioFrame:
    """Decode exactly one packet, rejecting incomplete or excess payload bytes."""
    _require_bytes(data, "data")
    if len(data) < HEADER.size:
        raise ValueError("incomplete audio header")
    if len(data) > HEADER.size + MAX_SAMPLES * 2:
        raise ValueError("audio packet is too large")
    magic, turn_id, generation_id, seq, sample_offset, samples = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError("invalid audio magic")
    if not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"sample count must be between 1 and {MAX_SAMPLES}")
    if len(data) != HEADER.size + samples * 2:
        raise ValueError("audio payload length does not match sample count")
    return AudioFrame(turn_id, generation_id, seq, sample_offset, data[HEADER.size:])


class SequenceGuard:
    """Validate a fixed turn/generation without allowing frames to switch it.

    Identity ordering is lexicographic: turn first, then generation within a
    turn. Old identities return False before sequence/payload validation;
    future identities raise ValueError. Only accepted current frames advance
    sequence, sample offset, and the cumulative inclusive max_samples budget.
    Construct a new guard for a new turn or generation.
    """

    def __init__(self, turn_id: int, generation_id: int, max_samples: int):
        _uint(turn_id, 32, "turn_id")
        _uint(generation_id, 32, "generation_id")
        _uint(max_samples, 64, "max_samples")
        self.turn_id = turn_id
        self.generation_id = generation_id
        self.max_samples = max_samples
        self._next_seq = 0
        self._sample_offset = 0

    def accept(self, frame: AudioFrame) -> bool:
        _uint(frame.turn_id, 32, "turn_id")
        _uint(frame.generation_id, 32, "generation_id")
        identity = (frame.turn_id, frame.generation_id)
        current = (self.turn_id, self.generation_id)
        if identity < current:
            return False
        if identity > current:
            raise ValueError("audio frame belongs to a future turn or generation")

        _uint(frame.seq, 32, "seq")
        _uint(frame.sample_offset, 64, "sample_offset")
        samples = _pcm_samples(frame.pcm)
        if frame.seq != self._next_seq:
            raise ValueError(f"expected sequence {self._next_seq}, got {frame.seq}")
        if frame.sample_offset != self._sample_offset:
            raise ValueError(
                f"expected sample offset {self._sample_offset}, got {frame.sample_offset}"
            )
        next_offset = self._sample_offset + samples
        if next_offset > self.max_samples:
            raise ValueError("audio exceeds cumulative max_samples budget")

        self._next_seq += 1
        self._sample_offset = next_offset
        return True


class PCMWindows:
    """Reassemble arbitrary byte chunks into fixed-size PCM16 sample windows.

    feed() allows empty chunks and retains an incomplete window, including a
    half sample. finish() drains an even tail without padding; an odd tail
    raises ValueError and remains buffered so its missing byte can be supplied.
    The retained buffer is always shorter than one window.
    """

    def __init__(self, window_samples: int):
        if type(window_samples) is not int or window_samples <= 0:
            raise ValueError("window_samples must be a positive integer")
        self._window_bytes = window_samples * 2
        self._pending = b""

    def feed(self, pcm_bytes: bytes) -> list[bytes]:
        _require_bytes(pcm_bytes, "pcm_bytes")
        data = self._pending + pcm_bytes
        complete_bytes = len(data) // self._window_bytes * self._window_bytes
        windows = [
            data[start:start + self._window_bytes]
            for start in range(0, complete_bytes, self._window_bytes)
        ]
        self._pending = data[complete_bytes:]
        return windows

    def finish(self) -> bytes:
        if len(self._pending) % 2:
            raise ValueError("incomplete PCM16 sample at end of stream")
        tail = self._pending
        self._pending = b""
        return tail
