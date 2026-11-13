"""Cooperative GPU cancellation with joined workers and bounded output.

Uses exp14's fixed CUDA adapters, without editing that experiment or its venv.
No ASR/VAD runs here: interruption is an explicit playback-position control.
"""
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'exp14'))
from logic import TextChunks
from models import Models, pcm16


PROMPT = '请介绍如何安排一次周末城市散步，从出门准备一直说到回家，详细一些。'
NEXT_PROMPT = '刚才先放一边。现在只说一句：好的，我们换个话题。'


def retained_history(segments, played):
    if type(played) is not int or played < 0:
        raise ValueError('invalid played offset')
    return ''.join(p['text'] for p in segments if p['end'] <= played)


class CancelModels(Models):
    def __init__(self):
        super().__init__(parts=('llm', 'tts'))

    def stream_text(self, text, stop, state, history=None):
        from transformers import TextIteratorStreamer, StoppingCriteria, StoppingCriteriaList
        torch, tok = self.torch, self.tokenizer
        instruction = ('你是中文语音助手。直接用一句中文回答，不要解释、编号或思考过程。' if history else
                       '你是中文语音助手。请用自然口语回答，用六到八个完整句子，不要标题、列表、编号或思考过程。')
        messages = [{'role':'system','content':instruction}]
        messages.extend(history or [])
        messages.append({'role':'user','content':text})
        state.update(thread_stopped=False, generated_tokens=0, token_steps=[], prompt_messages=messages)
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        batch = tok(prompt, return_tensors='pt').to('cuda')
        start = batch['input_ids'].shape[1]
        if start > 1024: raise ValueError('input exceeds 1024 tokens')
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=.2)
        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kw):
                seen = stop.is_set()
                state['token_steps'].append({'monotonic_ns':time.perf_counter_ns(),
                                            'tokens':input_ids.shape[1]-start,'stop':seen})
                return seen
        def work():
            try:
                with torch.inference_mode():
                    result = self.llm.generate(**batch, max_new_tokens=256 if not history else 64,
                        do_sample=False, temperature=1., top_p=1., top_k=0,
                        pad_token_id=tok.eos_token_id, streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([Stop()]))
                new = result[0, start:]
                state['generated_tokens'] = len(new)
                state['finish_reason'] = ('stop' if len(new) and int(new[-1]) == tok.eos_token_id
                    else 'cancelled' if stop.is_set() else 'length')
            except BaseException as exc:
                state['error'] = repr(exc); streamer.end()
            finally:
                state['generate_return_ns'] = time.perf_counter_ns()
        worker = threading.Thread(target=work, name='exp16-model-llm', daemon=False)
        worker.start()
        exhausted = False
        try:
            while True:
                try: part = next(streamer)
                except queue.Empty:
                    if not worker.is_alive(): break
                    continue
                except StopIteration:
                    exhausted = True; break
                if part: yield part
        finally:
            if not exhausted: stop.set()
            worker.join()
            state['thread_stopped'] = not worker.is_alive()
        if state.get('error'): raise RuntimeError(state['error'])


class Generation:
    def __init__(self, models, generation, prompt, history, queue_limit=100):
        self.models, self.generation, self.prompt, self.history = models, generation, prompt, history
        self.session_id = 'unset'
        self.stop = threading.Event()
        self.output = queue.Queue(queue_limit)
        self.texts = queue.Queue(2)
        self.events, self.segments = [], []
        self.state = dict(text='', llm={}, computed_samples=0, discarded_after_stop_samples=0,
                          queued_samples=0, llm_thread_stopped=False, tts_thread_stopped=False)
        self.llm = threading.Thread(target=self._llm, name='exp16-llm', daemon=False)
        self.tts = threading.Thread(target=self._tts, name='exp16-tts', daemon=False)

    def event(self, name, **fields):
        self.events.append(dict(event=name, component=name.split('_')[0],
            clock_domain='server_monotonic', monotonic_ns=time.perf_counter_ns(),
            session_id=self.session_id, turn_id=self.generation, generation_id=self.generation, **fields))

    def start(self):
        self.event('generation_start'); self.tts.start(); self.llm.start()

    def _put(self, target, value):
        while not self.stop.is_set():
            try: target.put(value, timeout=.02); return True
            except queue.Full: pass
        return False

    def _llm(self):
        iterator = None
        try:
            self.event('llm_start')
            chunks = TextChunks(max_chars=12)
            iterator = self.models.stream_text(self.prompt, self.stop, self.state['llm'], self.history)
            for piece in iterator:
                if self.stop.is_set(): break
                self.event('llm_piece', text=piece)
                self.state['text'] += piece
                for text in chunks.feed(piece):
                    if not self._put(self.texts, text): break
                if self.stop.is_set(): break
            if not self.stop.is_set():
                for text in chunks.finish(): self._put(self.texts, text)
        except BaseException as exc:
            self.state['llm_error'] = repr(exc); self.stop.set()
        finally:
            if iterator is not None: iterator.close()
            self.state['llm_thread_stopped'] = True
            self.event('llm_worker_returned')

    def _tts(self):
        offset = 0
        try:
            while not self.stop.is_set():
                try: text = self.texts.get(timeout=.02)
                except queue.Empty:
                    if self.state['llm_thread_stopped'] and self.texts.empty(): break
                    continue
                if self.stop.is_set(): break
                number = len(self.segments)
                self.event('tts_call_start', segment=number, text=text)
                data = bytearray()
                iterator = iter(self.models.tts(text))
                try:
                    for wave in iterator:
                        count = len(wave)
                        self.state['computed_samples'] += count
                        if self.stop.is_set():
                            self.state['discarded_after_stop_samples'] += count
                            break
                        data.extend(pcm16(wave))
                finally:
                    close = getattr(iterator, 'close', None)
                    if close: close()
                self.event('tts_call_return', segment=number, samples=len(data)//2,
                           stop=self.stop.is_set())
                if self.stop.is_set(): break
                if not data: raise RuntimeError('empty TTS')
                part = dict(type='segment', generation=self.generation, segment=number,
                            text=text, start=offset, end=offset+len(data)//2)
                self.segments.append(part.copy())
                if not self._put(self.output, part): break
                for i in range(0, len(data), 960):
                    pcm = bytes(data[i:i+960])
                    if not self._put(self.output, dict(type='audio', generation=self.generation,
                                    segment=number, offset=offset, pcm=pcm)): break
                    offset += len(pcm)//2
                    self.state['queued_samples'] = offset
        except BaseException as exc:
            self.state['tts_error'] = repr(exc); self.stop.set()
        finally:
            self.state['tts_thread_stopped'] = True
            self.event('tts_worker_returned')

    def cancel(self):
        if not self.stop.is_set():
            self.event('cancel_received'); self.stop.set(); self.event('stop_signal_set')
        discarded = 0
        while True:
            try:
                item = self.output.get_nowait()
                if item['type'] == 'audio': discarded += len(item['pcm'])//2
            except queue.Empty: break
        self.event('server_queue_cleared', discarded_samples=discarded)

    def pop(self, timeout=.005):
        if self.stop.is_set(): return None
        try:
            item = self.output.get(timeout=timeout)
            return None if self.stop.is_set() else item
        except queue.Empty: return None

    def finished(self): return not self.llm.is_alive() and not self.tts.is_alive()

    def join(self):
        self.llm.join(); self.tts.join()
        if self.stop.is_set():
            remaining = 0
            while True:
                try:
                    item = self.output.get_nowait()
                    if item['type'] == 'audio': remaining += len(item['pcm'])//2
                except queue.Empty: break
            while True:
                try: self.texts.get_nowait()
                except queue.Empty: break
            self.event('post_join_queue_cleared', discarded_samples=remaining)
        self.event('workers_joined', llm_stopped=not self.llm.is_alive(), tts_stopped=not self.tts.is_alive())
