"""Pure in-memory transport checks; no server, model, or tool execution."""

import unittest

from transport import SSEDecoder, frame_events


class FrameEventsTests(unittest.TestCase):
    def test_frames_named_and_unnamed_events_with_optional_done_payload(self):
        events = [
            {"event": "response.output_text.delta", "data": '{"delta":"你好🙂"}'},
            {"event": None, "data": "plain"},
        ]
        self.assertEqual(
            frame_events(events, done="[DONE]"),
            (
                'event: response.output_text.delta\ndata: {"delta":"你好🙂"}\n\n'
                "data: plain\n\ndata: [DONE]\n\n"
            ).encode("utf-8"),
        )

    def test_each_data_line_is_framed_with_lf_and_trailing_empty_lines_survive(self):
        self.assertEqual(
            frame_events([{"event": None, "data": "a\r\nb\rc\n\n"}]),
            b"data: a\ndata: b\ndata: c\ndata: \ndata: \n\n",
        )

    def test_empty_data_is_an_event_and_leading_spaces_are_preserved(self):
        self.assertEqual(
            frame_events([
                {"event": None, "data": ""},
                {"event": None, "data": "  value\n:literal\u2028text"},
            ]),
            "data: \n\ndata:   value\ndata: :literal\u2028text\n\n".encode("utf-8"),
        )

    def test_none_done_adds_nothing_but_empty_done_is_framed(self):
        self.assertEqual(frame_events([]), b"")
        self.assertEqual(frame_events([], done=""), b"data: \n\n")
        self.assertEqual(frame_events([], done="end\nmarker"), b"data: end\ndata: marker\n\n")

    def test_empty_event_name_is_written_explicitly(self):
        self.assertEqual(
            frame_events([{"event": "", "data": "x"}]),
            b"event: \ndata: x\n\n",
        )

    def test_event_names_cannot_inject_fields_or_line_endings(self):
        for name in ("delta\ndata: forged", "delta\rdata: forged", "delta\r\nnext"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                frame_events([{"event": name, "data": "x"}])


class SSEDecoderTests(unittest.TestCase):
    # Literal wire fixture and literal expectations are independent of the framer.
    unicode_wire = (
        '\ufeffevent: response.output_text.delta\r\ndata: {"delta":"你好🙂🚀"}\r\n\r\n'
        "data: 下一行🐼\n\ndata: [DONE]\r\r"
    ).encode("utf-8")
    unicode_events = [
        {"event": "response.output_text.delta", "data": '{"delta":"你好🙂🚀"}'},
        {"event": None, "data": "下一行🐼"},
        {"event": None, "data": "[DONE]"},
    ]

    def decode_chunks(self, chunks):
        decoder = SSEDecoder()
        events = []
        for chunk in chunks:
            events.extend(decoder.feed(chunk))
        events.extend(decoder.finish())
        return events

    def test_chinese_and_emoji_survive_every_single_byte_split(self):
        for split in range(len(self.unicode_wire) + 1):
            with self.subTest(split=split):
                self.assertEqual(
                    self.decode_chunks([self.unicode_wire[:split], self.unicode_wire[split:]]),
                    self.unicode_events,
                )

    def test_chinese_and_emoji_survive_one_byte_at_a_time(self):
        self.assertEqual(
            self.decode_chunks([bytes([byte]) for byte in self.unicode_wire]),
            self.unicode_events,
        )

    def test_framed_unicode_multiline_events_roundtrip_at_all_byte_boundaries(self):
        events = [
            {"event": "delta", "data": "中文🙂\n第二行🚀\n"},
            {"event": None, "data": ""},
        ]
        wire = frame_events(events, done="[DONE]")
        expected = [
            {"event": "delta", "data": "中文🙂\n第二行🚀\n"},
            {"event": None, "data": ""},
            {"event": None, "data": "[DONE]"},
        ]
        for split in range(len(wire) + 1):
            with self.subTest(split=split):
                self.assertEqual(self.decode_chunks([wire[:split], wire[split:]]), expected)
        self.assertEqual(self.decode_chunks([bytes([byte]) for byte in wire]), expected)

    def test_lf_crlf_and_cr_are_line_terminators(self):
        for ending in (b"\n", b"\r\n", b"\r"):
            with self.subTest(ending=ending):
                decoder = SSEDecoder()
                self.assertEqual(
                    decoder.feed(ending.join([b"event: delta", b"data: a", b"data: b", b"", b""])),
                    [{"event": "delta", "data": "a\nb"}],
                )
                self.assertEqual(decoder.finish(), [])

    def test_crlf_across_feeds_does_not_create_a_spurious_blank_line(self):
        decoder = SSEDecoder()
        self.assertEqual(decoder.feed(b"event: delta\r\ndata: first\r"), [])
        self.assertEqual(decoder.feed(b""), [])
        self.assertEqual(decoder.feed(b"\n"), [])
        self.assertEqual(decoder.feed(b"data: second\r"), [])
        self.assertEqual(decoder.feed(b"\n"), [])
        self.assertEqual(decoder.feed(b"\r"), [{"event": "delta", "data": "first\nsecond"}])
        self.assertEqual(decoder.feed(b"\n"), [])
        self.assertEqual(decoder.finish(), [])

    def test_partial_lines_are_buffered_until_a_blank_line_arrives(self):
        decoder = SSEDecoder()
        self.assertEqual(decoder.feed(b"ev"), [])
        self.assertEqual(decoder.feed(b"ent: delta\nda"), [])
        self.assertEqual(decoder.feed(b"ta: x\n"), [])
        self.assertEqual(decoder.feed(b"\n"), [{"event": "delta", "data": "x"}])

    def test_eof_discards_events_without_a_terminating_blank_line(self):
        for tail in (b"data: tail", b"data: tail\n", b"data: tail\r\n", b"data: tail\r",
                     b"event: done\ndata: [DONE]\n", b"event: done\n\n"):
            with self.subTest(tail=tail):
                decoder = SSEDecoder()
                self.assertEqual(decoder.feed(tail), [])
                self.assertEqual(decoder.finish(), [])

    def test_complete_event_survives_but_eof_tail_does_not(self):
        decoder = SSEDecoder()
        self.assertEqual(
            decoder.feed(b"data: complete\n\nevent: done\ndata: [DONE]\n"),
            [{"event": None, "data": "complete"}],
        )
        self.assertEqual(decoder.finish(), [])

    def test_comments_and_empty_blocks_never_emit_and_reset_event_name(self):
        self.assertEqual(
            self.decode_chunks([b"\n:\n: heartbeat\n\nevent: discarded\n:\n\ndata: x\n\n"]),
            [{"event": None, "data": "x"}],
        )

    def test_empty_data_is_distinct_from_absent_data(self):
        for wire, expected in (
            (b"data\n\n", ""),
            (b"data:\n\n", ""),
            (b"data: \n\n", ""),
            (b"data:\ndata:\n\n", "\n"),
            (b"data: x\ndata:\n\n", "x\n"),
        ):
            with self.subTest(wire=wire):
                self.assertEqual(self.decode_chunks([wire]), [{"event": None, "data": expected}])

    def test_multidata_uses_first_colon_and_removes_only_one_ascii_space(self):
        self.assertEqual(
            self.decode_chunks([
                b"event: delta\ndata: a:b\n: ignore\nunknown: ignored\n"
                b"data:  leading\ndata:\ttab\ndata\n\n"
            ]),
            [{"event": "delta", "data": "a:b\n leading\n\ttab\n"}],
        )

    def test_unknown_case_sensitive_fields_and_id_retry_are_ignored(self):
        self.assertEqual(
            self.decode_chunks([b"Event: ignored\nData: ignored\nid: 7\nretry: 1\n"
                                b" data: ignored\nunknown\ndata: real\n\n"]),
            [{"event": None, "data": "real"}],
        )

    def test_last_event_name_wins_and_empty_or_missing_names_return_none(self):
        self.assertEqual(
            self.decode_chunks([
                b"event: old\nevent: new\ndata: a\n\n"
                b"data: b\n\nevent: old\nevent:\ndata: c\n\n"
            ]),
            [{"event": "new", "data": "a"}, {"event": None, "data": "b"},
             {"event": None, "data": "c"}],
        )

    def test_only_one_leading_bom_is_removed_and_embedded_bom_is_preserved(self):
        self.assertEqual(
            self.decode_chunks(["\ufeff\ufeffdata: ignored\n\ndata: \ufeffkept\n\n".encode("utf-8")]),
            [{"event": None, "data": "\ufeffkept"}],
        )

    def test_finish_is_idempotent_and_rejects_all_later_feeds(self):
        decoder = SSEDecoder()
        self.assertEqual(decoder.feed(b"data: unfinished"), [])
        self.assertEqual(decoder.finish(), [])
        self.assertEqual(decoder.finish(), [])
        for chunk in (b"", b"\n\n", b"data: new\n\n"):
            with self.subTest(chunk=chunk), self.assertRaises(RuntimeError):
                decoder.feed(chunk)

    def test_invalid_utf8_is_strict_and_closes_the_decoder(self):
        for invalid in (b"\xff", b"\x80", b"\xc0\xaf", b"\xed\xa0\x80"):
            with self.subTest(invalid=invalid):
                decoder = SSEDecoder()
                with self.assertRaises(UnicodeDecodeError):
                    decoder.feed(b"data: " + invalid + b"\n\n")
                with self.assertRaises(RuntimeError):
                    decoder.feed(b"data: recovery\n\n")

    def test_truncated_utf8_including_bom_prefix_is_rejected_at_finish(self):
        for partial in (b"\xe4", b"data: \xf0\x9f\x99", b"\xef", b"\xef\xbb"):
            with self.subTest(partial=partial):
                decoder = SSEDecoder()
                self.assertEqual(decoder.feed(partial), [])
                with self.assertRaises(UnicodeDecodeError):
                    decoder.finish()
                with self.assertRaises(RuntimeError):
                    decoder.feed(b"\n\n")


if __name__ == "__main__":
    unittest.main()
