"""Explicit CUDA-only model adapters; all weights are loaded from fixed local files."""
import array
import queue
import sys
import threading
from pathlib import Path


def checked_input(pcm):
    if not pcm or len(pcm) % 2 or len(pcm) > 16000 * 15 * 2:
        raise ValueError('input must be nonempty PCM16, at most 15 seconds')
    return len(pcm) // 2


def pcm16(samples):
    result = array.array('h', (int(max(-1., min(1., float(v))) * 32767) for v in samples))
    if sys.byteorder != 'little':
        result.byteswap()
    return result.tobytes()


def non_silent_sample(samples, threshold=.01):
    return next((i for i, value in enumerate(samples) if abs(float(value)) >= threshold), None)


def finish_generation(thread, stop, exhausted):
    if not exhausted and thread.is_alive():
        stop.set()
    thread.join()


class Models:
    def __init__(self, parts=('asr', 'llm', 'tts', 'vad'), root='/opt/models'):
        import os
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        import numpy as np
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA required: CPU fallback forbidden')
        torch.set_num_threads(4)
        self.np, self.torch = np, torch
        self.parts = parts
        self.metadata = {'device': torch.cuda.get_device_name(), 'torch': torch.__version__,
                         'cuda': torch.version.cuda, 'cudnn': torch.backends.cudnn.version()}
        root = Path(root)
        if 'asr' in parts:
            from faster_whisper import WhisperModel
            self.whisper = WhisperModel(str(root/'faster-whisper-small'), device='cuda',
                                       compute_type='int8_float16', cpu_threads=4, num_workers=1)
            if self.whisper.model.device != 'cuda':
                raise RuntimeError('ASR did not use CUDA')
            self.metadata['asr'] = {'device': self.whisper.model.device,
                                    'compute_type': self.whisper.model.compute_type}
        if 'llm' in parts:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            directory = str(root/'Qwen3-0.6B')
            self.tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True)
            self.llm = AutoModelForCausalLM.from_pretrained(directory, local_files_only=True,
                               torch_dtype=torch.bfloat16).to('cuda').eval()
            if any(p.device.type != 'cuda' for p in self.llm.parameters()):
                raise RuntimeError('LLM not fully on CUDA')
            self.metadata['llm'] = {'device': str(self.llm.device), 'dtype': str(self.llm.dtype)}
        if 'tts' in parts:
            from kokoro import KModel, KPipeline
            directory = root/'Kokoro-82M-v1.1-zh'
            repo = 'hexgrad/Kokoro-82M-v1.1-zh'
            self.kmodel = KModel(repo_id=repo, config=str(directory/'config.json'),
                                model=str(directory/'kokoro-v1_1-zh.pth')).to('cuda').eval()
            self.voice = torch.load(directory/'voices/zf_001.pt', map_location='cpu', weights_only=True)
            self.kpipeline = KPipeline(lang_code='z', repo_id=repo, model=self.kmodel)
            if any(p.device.type != 'cuda' for p in self.kmodel.parameters()):
                raise RuntimeError('TTS not fully on CUDA')
            self.metadata['tts'] = {'device': str(self.kmodel.device),
                                    'dtype': str(next(self.kmodel.parameters()).dtype),
                                    'voice': 'zf_001', 'sample_rate': 24000}
        if 'vad' in parts:
            from silero_vad import load_silero_vad
            self.vad = load_silero_vad(onnx=False).eval()
            self.metadata['vad'] = {'device': 'cpu', 'window_samples': 512, 'sample_rate': 16000}

    def asr(self, pcm):
        checked_input(pcm)
        samples = self.np.frombuffer(pcm, dtype='<i2').astype('float32') / 32768
        segments, _ = self.whisper.transcribe(samples, language='zh', beam_size=1,
                 condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
        return ''.join(s.text for s in segments).strip()

    def speech_probability(self, pcm_window):
        samples = self.np.frombuffer(pcm_window, dtype='<i2').astype('float32') / 32768
        if len(samples) != 512:
            raise ValueError('Silero requires 512 samples at 16 kHz')
        with self.torch.inference_mode():
            return float(self.vad(self.torch.from_numpy(samples), 16000))

    def stream_text(self, text, stop, state=None):
        from transformers import TextIteratorStreamer, StoppingCriteria, StoppingCriteriaList
        state = state if state is not None else {}
        state.update(thread_stopped=False, generated_tokens=0, finish_reason=None)
        tok, torch = self.tokenizer, self.torch
        prompt = tok.apply_chat_template([
            {'role':'system','content':'你是中文语音助手。直接回答问题，用一到三句自然口语。不要思考过程、编号、表格或符号。'},
            {'role':'user','content':text}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        batch = tok(prompt, return_tensors='pt').to('cuda')
        if batch['input_ids'].shape[1] > 1024:
            raise ValueError('LLM input exceeds 1024 tokens')
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=2)
        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kw): return stop.is_set()
        def work():
            try:
                with torch.inference_mode():
                    output = self.llm.generate(**batch, max_new_tokens=96, do_sample=False,
                        temperature=1., top_p=1., top_k=0, pad_token_id=tok.eos_token_id,
                        streamer=streamer, stopping_criteria=StoppingCriteriaList([Stop()]))
                new = output[0, batch['input_ids'].shape[1]:]
                state['generated_tokens'] = len(new)
                state['finish_reason'] = ('stop' if len(new) and int(new[-1]) == tok.eos_token_id
                    else 'cancelled' if stop.is_set() else 'length' if len(new) >= 96 else 'unknown')
            except BaseException as exc:
                state['error'] = type(exc).__name__ + ': ' + str(exc)
                streamer.end()
        thread = threading.Thread(target=work, name='exp14-llm', daemon=False)
        thread.start()
        exhausted = False
        try:
            while True:
                try:
                    piece = next(streamer)
                except queue.Empty:
                    if not thread.is_alive():
                        break
                    continue
                except StopIteration:
                    exhausted = True
                    break
                if piece:
                    yield piece
        finally:
            finish_generation(thread, stop, exhausted)
            state['thread_stopped'] = not thread.is_alive()
        if state.get('error'):
            raise RuntimeError(state['error'])

    def tts(self, text):
        with self.torch.inference_mode():
            for result in self.kpipeline(text, voice=self.voice, speed=1.):
                audio = result.audio
                if audio is None:
                    raise RuntimeError('TTS returned no audio')
                yield audio.detach().cpu().numpy().astype('float32', copy=False)
