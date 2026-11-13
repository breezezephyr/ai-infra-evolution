"""Runtime-independent policies and metrics used by exp14."""
import asyncio
import unicodedata


class Endpoint:
    def __init__(self, tail_ms, sample_rate=16000, threshold=.5):
        if tail_ms <= 0 or sample_rate <= 0:
            raise ValueError('positive timing required')
        self.tail_samples = int(tail_ms * sample_rate / 1000)
        self.threshold = threshold
        self.last_speech_sample = None
        self.triggered = False

    def feed(self, probability, end_sample):
        if self.triggered:
            return False
        if probability >= self.threshold:
            self.last_speech_sample = end_sample
        elif (self.last_speech_sample is not None and
              end_sample - self.last_speech_sample >= self.tail_samples):
            self.triggered = True
            return True
        return False


class TextChunks:
    def __init__(self, full=False, max_chars=32):
        self.full = full
        self.max_chars = max_chars
        self.buffer = ''

    def feed(self, text):
        self.buffer += text
        if self.full:
            return []
        result = []
        while self.buffer:
            cut = next((i + 1 for i, c in enumerate(self.buffer[:self.max_chars])
                        if c in '。！？!?；;\n'), None)
            if cut is None:
                if len(self.buffer) < self.max_chars:
                    break
                cut = self.max_chars
            part, self.buffer = self.buffer[:cut], self.buffer[cut:]
            if part.strip():
                result.append(part)
        return result

    def finish(self):
        part, self.buffer = self.buffer, ''
        return [part] if part.strip() else []


async def joined_call(fn, *args):
    """Cancellation waits for the real worker; it does not interrupt native code."""
    worker = asyncio.create_task(asyncio.to_thread(fn, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(worker)
            break
        except asyncio.CancelledError:
            cancelled = True
            if worker.done():
                break
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError() from None
            raise
    if cancelled:
        if not worker.cancelled():
            worker.exception()
        raise asyncio.CancelledError()
    return result


def normalized_cer(reference, hypothesis):
    def normalize(text):
        return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                       if not c.isspace() and not unicodedata.category(c).startswith('P'))
    a, b = normalize(reference), normalize(hypothesis)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j-1] + (ca != cb)))
        prev = row
    return prev[-1] / len(a)
