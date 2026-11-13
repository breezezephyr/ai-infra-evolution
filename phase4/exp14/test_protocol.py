"""Functional tests for exp14's wire protocol and PCM stream handling.

Run without creating bytecode files:
    python3 -B -m unittest discover -s phase4/exp14 -p 'test_protocol.py' -v
"""

import importlib
import struct
import unittest
from dataclasses import is_dataclass


class ProtocolTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.protocol = importlib.import_module("protocol")
        except ModuleNotFoundError as exc:
            if exc.name != "protocol":
                raise
            self.fail("protocol.py has not been implemented")

    def frame(self, seq=0, offset=0, pcm=b"\x01\x00", turn=7, generation=3):
        return self.protocol.AudioFrame(turn, generation, seq, offset, pcm)


class AudioWireTests(ProtocolTestCase):
    # Independently specified bytes catch wrong endianness, layout, and byte counts.
    PACKET = bytes.fromhex(
        "50344131 04030201 14131211 24232221 0807060504030201 03000000 "
        "0000 ff7f 0080"
    )

    def test_pack_matches_independent_little_endian_wire_fixture(self):
        packet = self.protocol.pack_audio(
            0x01020304, 0x11121314, 0x21222324, 0x0102030405060708,
            b"\x00\x00\xff\x7f\x00\x80",
        )
        self.assertIsInstance(packet, bytes)
        self.assertEqual(packet, self.PACKET)

    def test_unpack_independent_fixture_returns_dataclass_and_unchanged_pcm(self):
        frame = self.protocol.unpack_audio(self.PACKET)
        self.assertTrue(is_dataclass(frame))
        self.assertIsInstance(frame, self.protocol.AudioFrame)
        self.assertEqual(
            (frame.turn_id, frame.generation_id, frame.seq, frame.sample_offset, frame.pcm),
            (0x01020304, 0x11121314, 0x21222324, 0x0102030405060708,
             b"\x00\x00\xff\x7f\x00\x80"),
        )

    def test_integer_field_zero_and_unsigned_maxima_round_trip(self):
        for fields in ((0, 0, 0, 0), (2**32 - 1,) * 3 + (2**64 - 1,)):
            with self.subTest(fields=fields):
                packet = self.protocol.pack_audio(*fields, b"\x00\x80")
                self.assertEqual(
                    self.protocol.unpack_audio(packet),
                    self.protocol.AudioFrame(*fields, b"\x00\x80"),
                )

    def test_pack_rejects_empty_odd_and_over_limit_pcm(self):
        for pcm in (b"", b"\x00", b"\x00" * 6399, b"\x00" * 6402):
            with self.subTest(length=len(pcm)), self.assertRaises(ValueError):
                self.protocol.pack_audio(0, 0, 0, 0, pcm)

    def test_pack_rejects_negative_overflow_and_non_integer_header_fields(self):
        for index, bits in enumerate((32, 32, 32, 64)):
            for bad in (-1, 2**bits, 1.5, True, "1", None):
                fields = [0, 0, 0, 0]
                fields[index] = bad
                with self.subTest(field=index, bad=bad), self.assertRaises(ValueError):
                    self.protocol.pack_audio(*fields, b"\x00\x00")

    def test_maximum_3200_sample_packet_is_accepted(self):
        pcm = b"\xff\x7f" * 3200
        packet = self.protocol.pack_audio(7, 3, 0, 0, pcm)
        self.assertEqual(len(packet), 6428)
        self.assertEqual(packet[24:28], b"\x80\x0c\x00\x00")
        self.assertEqual(self.protocol.unpack_audio(packet).pcm, pcm)

    def test_unpack_rejects_every_incomplete_header(self):
        for length in range(28):
            with self.subTest(length=length), self.assertRaises(ValueError):
                self.protocol.unpack_audio(self.PACKET[:length])

    def test_unpack_rejects_wrong_magic(self):
        with self.assertRaises(ValueError):
            self.protocol.unpack_audio(b"P4A2" + self.PACKET[4:])

    def test_unpack_rejects_truncated_extra_and_odd_payload(self):
        for packet in (
            self.PACKET[:28], self.PACKET[:-2], self.PACKET[:-1],
            self.PACKET + b"\x00", self.PACKET + b"\x00\x00",
        ):
            with self.subTest(length=len(packet)), self.assertRaises(ValueError):
                self.protocol.unpack_audio(packet)

    def test_unpack_rejects_announced_sample_count_mismatches_and_empty_pcm(self):
        for samples, payload in (
            (0, b""), (0, b"\x00\x00"), (1, b""),
            (2, b"\x00\x00"), (1, b"\x00\x00\x00\x00"),
        ):
            packet = struct.pack("<4sIIIQI", b"P4A1", 0, 0, 0, 0, samples) + payload
            with self.subTest(samples=samples, payload=payload), self.assertRaises(ValueError):
                self.protocol.unpack_audio(packet)

    def test_unpack_rejects_oversized_packet_and_huge_declared_sample_count(self):
        for samples, payload in (
            (3201, b"\x00\x00" * 3201), (3201, b""),
            (2**32 - 1, b""), (1, b"\x00\x00" * 3201),
        ):
            packet = struct.pack("<4sIIIQI", b"P4A1", 0, 0, 0, 0, samples) + payload
            with self.subTest(samples=samples, length=len(packet)), self.assertRaises(ValueError):
                self.protocol.unpack_audio(packet)


class SequenceGuardTests(ProtocolTestCase):
    def guard(self, max_samples=10):
        return self.protocol.SequenceGuard(7, 3, max_samples)

    def test_first_frame_starts_at_zero_and_offsets_count_samples(self):
        guard = self.guard(3)
        self.assertIs(guard.accept(self.frame(pcm=b"\x01\x00\x02\x00")), True)
        self.assertIs(guard.accept(self.frame(seq=1, offset=2)), True)

    def test_first_frame_rejects_nonzero_seq_or_offset_without_advancing(self):
        for seq, offset in ((1, 0), (0, 1)):
            guard = self.guard()
            with self.subTest(seq=seq, offset=offset):
                with self.assertRaises(ValueError):
                    guard.accept(self.frame(seq=seq, offset=offset))
                self.assertIs(guard.accept(self.frame()), True)

    def test_duplicate_and_skipped_seq_do_not_advance_state(self):
        for seq in (0, 2):
            guard = self.guard()
            guard.accept(self.frame())
            with self.subTest(seq=seq):
                with self.assertRaises(ValueError):
                    guard.accept(self.frame(seq=seq, offset=1))
                self.assertIs(guard.accept(self.frame(seq=1, offset=1)), True)

    def test_overlapping_and_gapped_offsets_do_not_advance_state(self):
        for offset in (0, 2, 100):
            guard = self.guard()
            guard.accept(self.frame())
            with self.subTest(offset=offset):
                with self.assertRaises(ValueError):
                    guard.accept(self.frame(seq=1, offset=offset))
                self.assertIs(guard.accept(self.frame(seq=1, offset=1)), True)

    def test_stale_turn_or_generation_is_dropped_without_using_sequence_or_budget(self):
        guard = self.guard(2)
        guard.accept(self.frame())
        # Generation is scoped to a turn: a larger old-turn generation is still old.
        for turn, generation in ((6, 99), (7, 2), (0, 0)):
            with self.subTest(turn=turn, generation=generation):
                self.assertIs(
                    guard.accept(self.frame(seq=99, offset=99, pcm=b"", turn=turn,
                                            generation=generation)), False,
                )
        self.assertIs(guard.accept(self.frame(seq=1, offset=1)), True)

    def test_future_turn_or_generation_raises_without_advancing_state(self):
        guard = self.guard(2)
        guard.accept(self.frame())
        for turn, generation in ((8, 0), (8, 3), (7, 4)):
            with self.subTest(turn=turn, generation=generation):
                with self.assertRaises(ValueError):
                    guard.accept(self.frame(seq=1, offset=1, turn=turn,
                                            generation=generation))
        self.assertIs(guard.accept(self.frame(seq=1, offset=1)), True)

    def test_cumulative_sample_limit_is_inclusive_and_rejection_is_atomic(self):
        guard = self.guard(3)
        guard.accept(self.frame(pcm=b"\x01\x00\x02\x00"))
        with self.assertRaises(ValueError):
            guard.accept(self.frame(seq=1, offset=2, pcm=b"\x03\x00\x04\x00"))
        self.assertIs(guard.accept(self.frame(seq=1, offset=2)), True)
        with self.assertRaises(ValueError):
            guard.accept(self.frame(seq=2, offset=3))

    def test_zero_sample_budget_rejects_any_current_audio(self):
        with self.assertRaises(ValueError):
            self.guard(0).accept(self.frame())

    def test_manually_constructed_invalid_current_frames_do_not_advance_state(self):
        for pcm in (b"", b"\x00", b"\x00\x00" * 3201):
            guard = self.guard()
            with self.subTest(length=len(pcm)):
                with self.assertRaises(ValueError):
                    guard.accept(self.frame(pcm=pcm))
                self.assertIs(guard.accept(self.frame()), True)

    def test_guard_rejects_negative_overflow_and_non_integer_frame_fields(self):
        for index, bits in enumerate((32, 32, 32, 64)):
            for bad in (-1, 2**bits, 0.0, True):
                guard = self.guard()
                fields = [7, 3, 0, 0]
                fields[index] = bad
                with self.subTest(field=index, bad=bad):
                    with self.assertRaises(ValueError):
                        guard.accept(self.protocol.AudioFrame(*fields, b"\x00\x00"))
                    self.assertIs(guard.accept(self.frame()), True)

    def test_guard_constructor_rejects_invalid_identity_and_budget(self):
        for fields in (
            (-1, 3, 10), (2**32, 3, 10), (7, -1, 10), (7, 2**32, 10),
            (7, 3, -1), (7, 3, 2**64), (True, 3, 10), (7, 3, 1.5),
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.protocol.SequenceGuard(*fields)


class PCMWindowsTests(ProtocolTestCase):
    def test_transport_frames_reassemble_into_512_sample_vad_windows(self):
        windows = self.protocol.PCMWindows(512)
        self.assertEqual(windows.feed(b"\x01\x00" * 320), [])
        self.assertEqual(
            windows.feed(b"\x02\x00" * 320),
            [b"\x01\x00" * 320 + b"\x02\x00" * 192],
        )
        self.assertEqual(windows.finish(), b"\x02\x00" * 128)

    def test_odd_byte_chunks_preserve_sample_boundaries(self):
        windows = self.protocol.PCMWindows(2)
        self.assertEqual(windows.feed(b"\x01"), [])
        self.assertEqual(windows.feed(b"\x00\x02"), [])
        self.assertEqual(windows.feed(b"\x00\x03\x00"), [b"\x01\x00\x02\x00"])
        self.assertEqual(windows.finish(), b"\x03\x00")

    def test_one_feed_returns_multiple_full_windows_and_even_tail(self):
        windows = self.protocol.PCMWindows(2)
        self.assertEqual(
            windows.feed(bytes.fromhex("0100 0200 0300 0400 0500")),
            [bytes.fromhex("0100 0200"), bytes.fromhex("0300 0400")],
        )
        self.assertEqual(windows.finish(), bytes.fromhex("0500"))

    def test_single_sample_windows_work_with_one_byte_at_a_time(self):
        windows = self.protocol.PCMWindows(1)
        output = []
        for value in b"\x00\x80\xff\x7f\xff\xff":
            output.extend(windows.feed(bytes([value])))
        self.assertEqual(output, [b"\x00\x80", b"\xff\x7f", b"\xff\xff"])
        self.assertEqual(windows.finish(), b"")

    def test_empty_feed_does_not_flush_or_pad_partial_window(self):
        windows = self.protocol.PCMWindows(2)
        self.assertEqual(windows.feed(b""), [])
        self.assertEqual(windows.feed(b"\x01"), [])
        self.assertEqual(windows.feed(b""), [])
        self.assertEqual(windows.feed(b"\x00"), [])
        self.assertEqual(windows.finish(), b"\x01\x00")

    def test_finish_rejects_half_sample_including_after_emitting_full_windows(self):
        for pcm in (b"\x01", b"\x01\x00\x02", b"\x01\x00\x02\x00\x03"):
            windows = self.protocol.PCMWindows(2)
            windows.feed(pcm)
            with self.subTest(length=len(pcm)), self.assertRaises(ValueError):
                windows.finish()

    def test_finish_consumes_even_tail_without_replaying_it(self):
        windows = self.protocol.PCMWindows(2)
        windows.feed(b"\x01\x00")
        self.assertEqual(windows.finish(), b"\x01\x00")
        self.assertEqual(windows.finish(), b"")

    def test_invalid_window_sizes_are_rejected(self):
        for size in (0, -1, 0.5, True, "512", None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.protocol.PCMWindows(size)


class ProtocolFlowTests(ProtocolTestCase):
    def test_wire_guard_and_vad_reassembly_preserve_full_pcm_with_late_frames(self):
        # Five real 20 ms frames at 16 kHz become three VAD windows plus 64 samples.
        pcm = struct.pack("<1600h", *range(-800, 800))
        guard = self.protocol.SequenceGuard(7, 3, 1600)
        windows = self.protocol.PCMWindows(512)
        output = []
        for seq in range(5):
            packet = self.protocol.pack_audio(7, 3, seq, seq * 320,
                                              pcm[seq * 640:(seq + 1) * 640])
            frame = self.protocol.unpack_audio(packet)
            self.assertIs(guard.accept(frame), True)
            output.extend(windows.feed(frame.pcm))
            stale = self.protocol.unpack_audio(
                self.protocol.pack_audio(7, 2, seq, seq * 320, b"\xff\x7f" * 320)
            )
            self.assertIs(guard.accept(stale), False)
        tail = windows.finish()
        self.assertEqual([len(window) for window in output], [1024, 1024, 1024])
        self.assertEqual(len(tail), 128)
        self.assertEqual(b"".join(output) + tail, pcm)

    def test_reassembly_is_independent_of_every_single_chunk_split(self):
        pcm = bytes.fromhex("0000 ff7f 0080 ffff 0100 0200 0300")
        for split in range(len(pcm) + 1):
            with self.subTest(split=split):
                windows = self.protocol.PCMWindows(3)
                output = windows.feed(pcm[:split]) + windows.feed(pcm[split:])
                self.assertEqual(output, [pcm[:6], pcm[6:12]])
                self.assertEqual(windows.finish(), pcm[12:])


if __name__ == "__main__":
    unittest.main()
