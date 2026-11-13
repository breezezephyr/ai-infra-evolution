"""CPU ONLY: real incremental SSE parser; no model, torch, GPU or HTTP calls.

Run: python3 -B -m unittest discover -s phase5/exp29 -p test_sse.py -v
"""
import json
import unittest

try:
    from experiment import SSEParser, SSEProtocolError
except ImportError:
    SSEParser = None
    SSEProtocolError = ValueError


def frame(value, newline="\n"):
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ("data: " + data + newline + newline).encode("utf-8")


ROLE = {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
TEXT = {"choices": [{"index": 0, "delta": {"content": "你好，世界"}, "finish_reason": None}]}
END = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
USAGE = {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}}


class TestSSECPU(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SSEParser, "CPU SSE parser must exist before these tests can pass")

    def parse(self, chunks):
        parser = SSEParser()
        for chunk in chunks:
            parser.feed(chunk)
        parser.finish()
        return parser

    def test_utf8_crlf_and_every_possible_two_piece_split(self):
        wire = b": keepalive\r\n\r\n" + b"".join(frame(x, "\r\n") for x in (ROLE, TEXT, END, USAGE, "[DONE]"))
        for cut in range(len(wire) + 1):
            with self.subTest(cut=cut):
                parser = self.parse([wire[:cut], wire[cut:]])
                self.assertEqual(parser.text, "你好，世界")
                self.assertEqual(bytes(parser.raw), wire)
                self.assertEqual(parser.usage, {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13})
                self.assertEqual(parser.finish_reason, "stop")
                self.assertTrue(parser.done)

    def test_one_byte_chunks_multiline_data_and_cr_line_endings(self):
        multiline = b'data: {"choices":\rdata: [{"index":0,"delta":{"content":"A"},"finish_reason":null}]}\r\r'
        wire = multiline + b"".join(frame(x, "\r") for x in (END, USAGE, "[DONE]"))
        parser = self.parse([wire[i:i + 1] for i in range(len(wire))])
        self.assertEqual(parser.text, "A")
        self.assertEqual(bytes(parser.raw), wire)

    def test_controls_and_empty_content_are_not_first_body(self):
        parser = SSEParser()
        parser.feed(frame(ROLE) + frame({"choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": None}]}))
        self.assertEqual(parser.text, "")
        parser.feed(frame(TEXT))
        self.assertEqual(parser.text, "你好，世界")

    def test_missing_or_out_of_order_terminals_fail(self):
        for parts in ((TEXT,), (TEXT, END), (TEXT, END, USAGE),
                      (TEXT, "[DONE]"), (TEXT, USAGE, END, "[DONE]"),
                      (TEXT, END, "[DONE]"), (TEXT, END, END, USAGE, "[DONE]"),
                      (TEXT, END, USAGE, USAGE, "[DONE]"),
                      (TEXT, END, USAGE, "[DONE]", TEXT),
                      (TEXT, END, TEXT, USAGE, "[DONE]"),
                      (TEXT, END, USAGE, "[DONE]", "[DONE]")):
            with self.subTest(parts=parts), self.assertRaises(SSEProtocolError):
                self.parse([b"".join(frame(x) for x in parts)])

    def test_error_event_and_malformed_payload_never_pass(self):
        for wire in (b'event: error\ndata: {"error":"worker failed"}\n\n',
                     frame({"error": {"message": "worker failed"}}),
                     b"data: {broken}\n\n", b"data: []\n\n",
                     b"data: \xff\n\n",
                     frame({"choices": [{"index": 0, "delta": {}, "finish_reason": "error"}]}),
                     frame({"choices": [{"index": 0, "delta": {"content": 7}, "finish_reason": None}]})):
            with self.subTest(wire=wire), self.assertRaises(SSEProtocolError):
                self.parse([wire])

    def test_usage_counts_and_frame_termination_are_checked(self):
        for usage in ({"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 99},
                      {"prompt_tokens": True, "completion_tokens": 4, "total_tokens": 5},
                      {"prompt_tokens": 9, "completion_tokens": -1, "total_tokens": 8}):
            with self.subTest(usage=usage), self.assertRaises(SSEProtocolError):
                self.parse([frame(TEXT) + frame(END) + frame({"choices": [], "usage": usage}) + frame("[DONE]")])
        with self.assertRaises(SSEProtocolError):
            self.parse([frame(TEXT) + frame(END) + frame(USAGE) + b"data: [DONE]\n"])
        with self.assertRaises(SSEProtocolError):
            self.parse([frame(TEXT) + b"data: \xe4"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
