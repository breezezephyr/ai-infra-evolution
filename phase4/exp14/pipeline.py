"""One true model reply; bounded thread queues, cooperative stop and worker joining."""
import asyncio
import queue
import threading
from logic import TextChunks, joined_call
from models import pcm16

_END = object()


def _next(iterator):
    return next(iterator, _END)


async def generate_reply(models, pcm, mode, emit, event, stop, state):
    if mode not in ('A','B','C'):
        raise ValueError('unknown mode')
    state.update(llm={}, text='', asr_text=None, tts_worker_returned=False,
                 cancel_signal_set=False, output_samples=0, tts_generated_samples=0)
    event('asr_start')
    recognized = await joined_call(models.asr, pcm)
    state['asr_text'] = recognized
    event('asr_end', text=recognized)
    if not recognized:
        raise ValueError('empty ASR transcript')
    texts = queue.Queue(maxsize=2)
    audio = queue.Queue(maxsize=100)
    worker_error = []
    chunks = TextChunks(full=mode != 'C', max_chars=32)
    iterator = models.stream_text(recognized, stop, state['llm'])

    def put_thread(q, value):
        while not stop.is_set():
            try:
                q.put(value, timeout=.05)
                return True
            except queue.Full:
                continue
        return False

    async def put_text(value):
        while not stop.is_set():
            try:
                texts.put_nowait(value)
                return
            except queue.Full:
                await asyncio.sleep(.005)
        raise asyncio.CancelledError()

    async def produce():
        event('llm_start')
        first = True
        try:
            while not stop.is_set():
                part = await joined_call(_next, iterator)
                if part is _END:
                    break
                if first:
                    event('first_text'); first = False
                state['text'] += part
                for text in chunks.feed(part):
                    event('tts_text_submitted', text=text)
                    await put_text(text)
            event('llm_end', **state['llm'])
            for text in chunks.finish():
                event('tts_text_submitted', text=text)
                await put_text(text)
            await put_text(_END)
        finally:
            await joined_call(iterator.close)

    def synthesize():
        first = True
        try:
            while not stop.is_set():
                try:
                    text = texts.get(timeout=.05)
                except queue.Empty:
                    continue
                if text is _END:
                    break
                event('tts_start', text=text)
                for wave in models.tts(text):
                    if stop.is_set():
                        break
                    event('tts_pcm_chunk', samples=len(wave))
                    state['tts_generated_samples'] += len(wave)
                    if first:
                        event('first_pcm'); first = False
                    data = pcm16(wave)
                    for offset in range(0,len(data),960):
                        if not put_thread(audio,data[offset:offset+960]):
                            break
                event('tts_part_end')
        except BaseException as exc:
            worker_error.append(exc)
        finally:
            state['tts_worker_returned'] = True

    thread = threading.Thread(target=synthesize, name='exp14-tts', daemon=False)
    thread.start()
    producer = asyncio.create_task(produce())
    normal = False
    try:
        first_sent = True
        while True:
            if producer.done() and not producer.cancelled() and producer.exception():
                raise producer.exception()
            if worker_error:
                raise worker_error[0]
            try:
                data = audio.get_nowait()
            except queue.Empty:
                if state['tts_worker_returned'] and audio.empty():
                    break
                await asyncio.sleep(.002)
                continue
            await emit(data)
            state['output_samples'] += len(data)//2
            if first_sent:
                event('first_audio_sent'); first_sent=False
        await producer
        if not state['output_samples']:
            raise ValueError('empty TTS output')
        if state['output_samples'] != state['tts_generated_samples']:
            raise RuntimeError('generated audio was not completely delivered')
        state['finish_reason'] = state['llm'].get('finish_reason','unknown')
        normal = True
    finally:
        if not normal:
            stop.set(); state['cancel_signal_set']=True
        if not producer.done():
            producer.cancel()
        async def cleanup():
            await asyncio.gather(producer, return_exceptions=True)
            await joined_call(thread.join)
        cleanup_task = asyncio.create_task(cleanup())
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                stop.set(); state['cancel_signal_set']=True
        cleanup_task.result()
        state['tts_thread_stopped'] = not thread.is_alive()
        event('workers_joined', llm=state['llm'].get('thread_stopped'),
              tts=state['tts_thread_stopped'])
