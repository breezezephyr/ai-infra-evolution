"""In-memory SSE transport experiment helpers; no HTTP or browser involved.

Parsing reference (only the field/line/data subset is implemented):
https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream
"""

import codecs


def frame_events(events: list[dict], done: str | None = None) -> bytes:
    """Encode string payloads as UTF-8 SSE frames, using LF throughout.

    Serialize recipe objects to ``data`` strings before calling this helper.
    CRLF and CR inside data are normalized to LF. Trailing/empty data lines
    survive. Event names cannot contain CR/LF. ``done is not None`` appends
    an unnamed event carrying that exact payload (usually ``[DONE]``).
    """
    frames = []
    framed_events = events if done is None else [*events, {"event": None, "data": done}]
    for item in framed_events:
        name = item["event"]
        if name is not None:
            if "\r" in name or "\n" in name:
                raise ValueError("event name cannot contain CR or LF")
            frames.append(f"event: {name}\n")
        data = item["data"].replace("\r\n", "\n").replace("\r", "\n")
        frames.extend(f"data: {line}\n" for line in data.split("\n"))
        frames.append("\n")
    return "".join(frames).encode("utf-8")


class SSEDecoder:
    """Incremental UTF-8/line/data parser for this experiment's SSE subset.

    Missing/empty event names return None, rather than EventSource's "message".
    One initial BOM is ignored. LF, CRLF and CR end lines; only a blank line
    dispatches data. Comments and unsupported fields (including id/retry) are
    ignored. This helper does not implement reconnects or browser dispatch.

    UTF-8 is deliberately strict: malformed bytes in feed(), or a truncated
    code point at finish(), raise UnicodeDecodeError and close the decoder.
    This policy makes no claim of matching browser error recovery. A failing
    feed is decoded before parsing, so no events from that call are returned.
    """

    def __init__(self):
        self._utf8 = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._at_start = True
        self._skip_lf = False
        self._closed = False
        self._line: list[str] = []
        self._data: list[str] = []
        self._event: str | None = None

    def feed(self, chunk: bytes) -> list[dict]:
        """Return newly completed events; reject feeds after close, even b''."""
        if self._closed:
            raise RuntimeError("SSEDecoder is closed")
        try:
            text = self._utf8.decode(chunk, final=False)
        except UnicodeDecodeError:
            self._closed = True
            self._discard_pending()
            raise
        if self._at_start and text:
            self._at_start = False
            text = text.removeprefix("\ufeff")

        events = []
        for char in text:
            if self._skip_lf:
                self._skip_lf = False
                if char == "\n":
                    continue
            if char in ("\r", "\n"):
                self._process_line("".join(self._line), events)
                self._line.clear()
                # Process CR immediately; swallow its optional LF, even if
                # the next byte/character arrives in a later feed call.
                self._skip_lf = char == "\r"
            else:
                self._line.append(char)
        return events

    def finish(self) -> list[dict]:
        """Validate UTF-8 EOF and discard pending data; repeated calls return [].

        EOF does not supply a blank line or invent a completion event. The
        decoder remains closed even when UTF-8 finalization raises.
        """
        if self._closed:
            return []
        self._closed = True
        try:
            self._utf8.decode(b"", final=True)
        finally:
            self._discard_pending()
        return []

    def _discard_pending(self):
        self._line.clear()
        self._data.clear()
        self._event = None

    def _process_line(self, line: str, events: list[dict]):
        if not line:
            if self._data:
                events.append({"event": self._event, "data": "\n".join(self._data)})
            self._data.clear()
            self._event = None
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                self._event = value or None
            elif field == "data":
                self._data.append(value)
