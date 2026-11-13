// Shared by the page, AudioWorklet and Node tests. No browser objects at import time.
export const INPUT_RATE = 16000;
export const OUTPUT_RATE = 24000;
export const QUEUE_SAMPLES = 48000;
export const SILENCE = Object.freeze({ threshold_pcm16: 120, window_ms: 10,
  method: 'non_overlapping_rendered_rms', comparison: '>=', partial_window: 'actual_count' });
const HEADER_BYTES = 28;
const MAX_PACKET_SAMPLES = 3200;

function viewOf(data) {
  if (data instanceof ArrayBuffer) return new DataView(data);
  if (ArrayBuffer.isView(data)) return new DataView(data.buffer, data.byteOffset, data.byteLength);
  throw new TypeError('expected ArrayBuffer or typed array');
}
function uint(value, bits, name) {
  if (!Number.isSafeInteger(value) || value < 0 || (bits === 32 && value >= 2 ** 32)) {
    throw new Error(`invalid ${name}`);
  }
}
function ascii(view, offset, count) {
  return String.fromCharCode(...new Uint8Array(view.buffer, view.byteOffset + offset, count));
}

export function parseWav(data) {
  const view = viewOf(data);
  if (view.byteLength < 12 || ascii(view, 0, 4) !== 'RIFF' || ascii(view, 8, 4) !== 'WAVE'
      || view.getUint32(4, true) + 8 !== view.byteLength) throw new Error('invalid RIFF WAV length');
  let format = null, audio = null, offset = 12;
  while (offset < view.byteLength) {
    if (offset + 8 > view.byteLength) throw new Error('truncated WAV chunk');
    const tag = ascii(view, offset, 4), size = view.getUint32(offset + 4, true), start = offset + 8;
    if (start + size > view.byteLength) throw new Error('truncated WAV data');
    if (tag === 'fmt ') {
      if (format || size < 16) throw new Error('invalid WAV format chunk');
      format = { codec: view.getUint16(start, true), channels: view.getUint16(start + 2, true),
        rate: view.getUint32(start + 4, true), byte_rate: view.getUint32(start + 8, true),
        align: view.getUint16(start + 12, true), bits: view.getUint16(start + 14, true) };
    } else if (tag === 'data') {
      if (audio || !size || size % 2) throw new Error('invalid PCM16 data');
      audio = { start, size };
    }
    offset = start + size + size % 2;
  }
  if (offset !== view.byteLength || !format || !audio || format.codec !== 1 || format.channels !== 1
      || format.rate !== INPUT_RATE || format.byte_rate !== 32000 || format.align !== 2 || format.bits !== 16) {
    throw new Error('expected mono 16000 Hz PCM16 WAV');
  }
  const pcm = new Int16Array(audio.size / 2);
  for (let i = 0; i < pcm.length; i++) pcm[i] = view.getInt16(audio.start + i * 2, true);
  if (pcm.length > INPUT_RATE * 15) throw new Error('input exceeds 15 seconds');
  return { sample_rate: INPUT_RATE, pcm };
}

export function packAudio({ turn_id = 1, generation_id = 1, seq, sample_offset, pcm }) {
  uint(turn_id, 32, 'turn_id'); uint(generation_id, 32, 'generation_id');
  uint(seq, 32, 'seq'); uint(sample_offset, 64, 'sample_offset');
  if (!(pcm instanceof Int16Array) || !pcm.length || pcm.length > MAX_PACKET_SAMPLES) {
    throw new Error('invalid PCM16 sample count');
  }
  const buffer = new ArrayBuffer(HEADER_BYTES + pcm.length * 2), view = new DataView(buffer);
  new Uint8Array(buffer, 0, 4).set([80, 52, 65, 49]);
  view.setUint32(4, turn_id, true); view.setUint32(8, generation_id, true);
  view.setUint32(12, seq, true); view.setBigUint64(16, BigInt(sample_offset), true);
  view.setUint32(24, pcm.length, true);
  for (let i = 0; i < pcm.length; i++) view.setInt16(HEADER_BYTES + i * 2, pcm[i], true);
  return buffer;
}

export function unpackAudio(data) {
  const view = viewOf(data);
  if (view.byteLength < HEADER_BYTES || ascii(view, 0, 4) !== 'P4A1') throw new Error('invalid audio header');
  const count = view.getUint32(24, true), offset = view.getBigUint64(16, true);
  if (!count || count > MAX_PACKET_SAMPLES || view.byteLength !== HEADER_BYTES + count * 2
      || offset > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('invalid audio payload/count/offset');
  const pcm = new Int16Array(count);
  for (let i = 0; i < count; i++) pcm[i] = view.getInt16(HEADER_BYTES + i * 2, true);
  return { turn_id: view.getUint32(4, true), generation_id: view.getUint32(8, true),
    seq: view.getUint32(12, true), sample_offset: Number(offset), count, pcm };
}

// A fixed 10ms RMS window rejects tiny noise/impulses. The event points back to
// the first threshold-crossing rendered sample in the first active window.
class SilenceDetector {
  constructor(rate) {
    this.window = Math.round(rate * SILENCE.window_ms / 1000);
    this.threshold = SILENCE.threshold_pcm16 / 32768;
    this.count = 0; this.energy = 0; this.candidate = null; this.found = false;
  }
  push(value, context_time_s, source_sample) {
    if (this.found) return null;
    this.count++; this.energy += value * value;
    if (!this.candidate && Math.abs(value) >= this.threshold) {
      this.candidate = { type: 'first_non_silent_render', context_time_s, source_sample };
    }
    return this.count >= this.window ? this.finishWindow() : null;
  }
  finishWindow() {
    let event = null;
    if (this.count && this.energy >= this.threshold ** 2 * this.count) {
      event = this.candidate; this.found = true;
    }
    this.count = 0; this.energy = 0; this.candidate = null;
    return event;
  }
}

export class PlaybackState {
  constructor({ turn_id = 1, generation_id = 1, run_id = '', device_rate = 48000,
    max_queue_samples = QUEUE_SAMPLES } = {}) {
    uint(turn_id, 32, 'turn_id'); uint(generation_id, 32, 'generation_id');
    if (!Number.isFinite(device_rate) || device_rate < 8000 || device_rate > 384000
        || !Number.isInteger(max_queue_samples) || max_queue_samples < 1 || max_queue_samples > QUEUE_SAMPLES) {
      throw new Error('invalid playback rate/queue');
    }
    this.turn_id = turn_id; this.generation_id = generation_id; this.run_id = run_id;
    this.rate = device_rate; this.step = OUTPUT_RATE / device_rate;
    this.buffer = new Float32Array(max_queue_samples); this.head = 0; this.queued = 0;
    this.received = 0; this.consumed = 0; this.seq = 0; this.phase = 0;
    this.terminal = false; this.renderStarted = false; this.drainReported = false;
    this.starving = false; this.missingDeviceFrames = 0; this.underrunEvents = 0;
    this.detector = new SilenceDetector(device_rate);
  }
  enqueue(packet, run_id = this.run_id) {
    if (run_id !== this.run_id) return false;
    const frame = unpackAudio(packet);
    if (frame.turn_id < this.turn_id || (frame.turn_id === this.turn_id && frame.generation_id < this.generation_id)) return false;
    if (frame.turn_id !== this.turn_id || frame.generation_id !== this.generation_id) throw new Error('future turn/generation');
    if (this.terminal) throw new Error('audio after terminal');
    if (frame.seq !== this.seq || frame.sample_offset !== this.received) throw new Error('audio sequence/offset gap');
    if (this.queued + frame.count > this.buffer.length) throw new Error('playback queue exceeds 48000 source samples');
    if (this.received + frame.count > OUTPUT_RATE * 30) throw new Error('output exceeds 30 seconds');
    for (let i = 0; i < frame.count; i++) {
      this.buffer[(this.head + this.queued + i) % this.buffer.length] = frame.pcm[i] / 32768;
    }
    this.queued += frame.count; this.received += frame.count; this.seq++;
    return true;
  }
  markTerminal(run_id = this.run_id) {
    if (run_id !== this.run_id) return false;
    this.terminal = true;
    return true;
  }
  snapshot() {
    return { received_samples: this.received, consumed_samples: this.consumed,
      queued_samples: this.queued, source_fraction: this.phase,
      underrun_samples: Math.floor(this.missingDeviceFrames * this.step + 1e-7),
      underrun_device_frames: this.missingDeviceFrames, underrun_events: this.underrunEvents,
      terminal: this.terminal, drained: this.terminal && this.queued === 0 };
  }
  render(output, context_time_s) {
    output.fill(0);
    const events = [];
    const emit = event => { if (event) events.push(event); };
    for (let i = 0; i < output.length; i++) {
      const time = context_time_s + i / this.rate;
      const finished = this.terminal && this.queued === 0;
      if (finished) {
        if (!this.drainReported) {
          if (this.starving) emit({ type: 'underrun_end', context_time_s: time });
          this.starving = false;
          emit(this.detector.finishWindow());
          emit({ type: 'playback_drained', context_time_s: time, source_sample: this.consumed });
          this.drainReported = true;
        }
        break;
      }
      const enough = this.queued > 0 && (this.phase === 0 || this.queued > 1 || this.terminal)
        && (this.terminal || this.phase + this.step <= this.queued + 1e-9);
      if (!enough) {
        // Only the active audio interval counts. The initial server wait is free.
        if (this.received > 0) {
          if (!this.starving) { this.underrunEvents++; emit({ type: 'underrun_start', context_time_s: time }); }
          this.starving = true; this.missingDeviceFrames++;
          if (this.renderStarted) emit(this.detector.push(0, time, null));
        }
        continue;
      }
      if (this.starving) emit({ type: 'underrun_end', context_time_s: time });
      this.starving = false;
      const source = this.consumed + this.phase;
      const left = this.buffer[this.head];
      const right = this.queued > 1 ? this.buffer[(this.head + 1) % this.buffer.length] : left;
      const value = left + (right - left) * this.phase;
      output[i] = value;
      if (!this.renderStarted) {
        emit({ type: 'first_pcm_render', context_time_s: time, source_sample: source }); this.renderStarted = true;
      }
      emit(this.detector.push(output[i], time, source));
      const next = this.phase + this.step;
      const advance = Math.min(this.queued, Math.floor(next + 1e-9));
      this.head = (this.head + advance) % this.buffer.length;
      this.queued -= advance; this.consumed += advance;
      this.phase = this.queued === 0 && this.terminal ? 0 : next - advance;
      if (Math.abs(this.phase) < 1e-9) this.phase = 0;
    }
    // A block ending exactly on the last sample must report drain now.
    if (this.terminal && !this.queued && !this.drainReported) {
      emit(this.detector.finishWindow());
      emit({ type: 'playback_drained', context_time_s: context_time_s + output.length / this.rate,
        source_sample: this.consumed });
      this.drainReported = true; this.starving = false;
    }
    return { ...this.snapshot(), events };
  }
}

export function mapContextToPerformance(context_time_s, anchor) {
  if (!anchor || ![context_time_s, anchor.context_time_s, anchor.performance_before_ms,
    anchor.performance_after_ms].every(Number.isFinite)) return null;
  return (anchor.performance_before_ms + anchor.performance_after_ms) / 2
    + (context_time_s - anchor.context_time_s) * 1000;
}
export function estimateOutputTime(context_time_s, stamp) {
  if (!stamp || ![context_time_s, stamp.contextTime, stamp.performanceTime].every(Number.isFinite)
      || stamp.performanceTime <= 0 || stamp.contextTime < 0
      || (stamp.contextTime === 0 && stamp.performanceTime === 0)) return null;
  return stamp.performanceTime + (context_time_s - stamp.contextTime) * 1000;
}
export function referenceSampleMapping(sample, frames) {
  if (!Number.isInteger(sample) || sample < 0) return null;
  const frame = frames.find(f => (sample === 0 ? f.sample_offset === 0 : f.sample_offset < sample)
    && sample <= f.sample_offset + f.count);
  if (!frame) return null;
  return { reference_sample: sample, frame_sample_offset: frame.sample_offset,
    frame_count: frame.count, frame_send_performance_ms: frame.performance_ms,
    performance_ms: frame.performance_ms + (sample - frame.sample_offset) / INPUT_RATE * 1000,
    method: 'actual_frame_send_plus_sample_offset', clock_domain: 'browser_performance',
    kind: 'synthetic_input_sample_replay_estimate' };
}

// Main-thread accounting also includes packets still in the MessagePort. Acks
// advance only on validated render reports, never when a WS packet arrives.
export class OutputLedger {
  constructor(run_id, turn_id = 1, generation_id = 1) {
    this.run_id = run_id; this.turn_id = turn_id; this.generation_id = generation_id;
    this.seq = 0; this.received = 0; this.consumed = 0;
  }
  accept(packet, run_id = this.run_id) {
    if (run_id !== this.run_id) return null;
    const frame = unpackAudio(packet);
    if (frame.turn_id < this.turn_id || (frame.turn_id === this.turn_id && frame.generation_id < this.generation_id)) return null;
    if (frame.turn_id !== this.turn_id || frame.generation_id !== this.generation_id) throw new Error('future turn/generation');
    if (frame.seq !== this.seq || frame.sample_offset !== this.received) throw new Error('audio sequence/offset gap');
    if (this.received + frame.count - this.consumed > QUEUE_SAMPLES) throw new Error('in-flight playback queue exceeds 48000 samples');
    if (this.received + frame.count > OUTPUT_RATE * 30) throw new Error('output exceeds 30 seconds');
    this.received += frame.count; this.seq++;
    return frame;
  }
  progress(message) {
    if (message.run_id !== this.run_id) return false;
    const consumed = message.consumed_samples, received = message.received_samples;
    if (!Number.isInteger(consumed) || !Number.isInteger(received) || consumed < this.consumed
        || consumed > received || received > this.received || received < 0) throw new Error('invalid render acknowledgement');
    this.consumed = consumed;
    return true;
  }
  ack() { return { type: 'ack', samples: this.consumed }; }
}

export async function sendInput(pcm, { send, now = () => performance.now(),
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), signal,
  onEvent = () => {}, turn_id = 1, generation_id = 1 } = {}) {
  if (!(pcm instanceof Int16Array) || !pcm.length || pcm.length > INPUT_RATE * 15) throw new Error('invalid input PCM');
  const started = now(), frames = [];
  let previousTime = null, previousCount = 0;
  const checkAbort = () => { if (signal?.aborted) throw new Error('input aborted'); };
  const waitUntil = async target => {
    while (now() < target) { checkAbort(); await sleep(target - now()); }
    checkAbort();
  };
  for (let offset = 0, seq = 0; offset < pcm.length; offset += 320, seq++) {
    const count = Math.min(320, pcm.length - offset);
    const planned = started + offset / INPUT_RATE * 1000;
    await waitUntil(Math.max(planned, previousTime === null ? planned : previousTime + previousCount / INPUT_RATE * 1000));
    const packet = packAudio({ turn_id, generation_id, seq, sample_offset: offset, pcm: pcm.subarray(offset, offset + count) });
    const performance_ms = now(); send(packet);
    const event = { type: 'input_frame_sent', seq, sample_offset: offset, count,
      performance_ms, planned_performance_ms: planned, clock_domain: 'browser_performance' };
    frames.push(event); onEvent(event); previousTime = performance_ms; previousCount = count;
  }
  await waitUntil(previousTime + previousCount / INPUT_RATE * 1000);
  send(JSON.stringify({ type: 'input_end' }));
  const input_end_perf_ms = now();
  onEvent({ type: 'input_end_sent', performance_ms: input_end_perf_ms, samples: pcm.length,
    clock_domain: 'browser_performance' });
  return { frame_sends: frames, input_start_perf_ms: started, input_end_perf_ms,
    sent_samples: pcm.length, complete: true };
}

export function registerPlaybackWorklet(scope = globalThis) {
  class PCMPlayer extends scope.AudioWorkletProcessor {
    constructor(options) {
      super();
      this.state = new PlaybackState({ ...options.processorOptions, device_rate: scope.sampleRate });
      this.elapsed = 0; this.pending = []; this.lastReportedDrain = false;
      this.port.onmessage = ({ data }) => {
        if (data.run_id !== this.state.run_id) return;
        try {
          if (data.type === 'audio') this.state.enqueue(data.packet, data.run_id);
          else if (data.type === 'terminal') this.state.markTerminal(data.run_id);
        } catch (error) {
          this.state.markTerminal();
          this.port.postMessage({ type: 'error', run_id: this.state.run_id, message: error.message });
        }
      };
    }
    process(_inputs, outputs) {
      const output = outputs[0]?.[0];
      if (!output) return true;
      const result = this.state.render(output, scope.currentTime);
      this.elapsed += output.length; this.pending.push(...result.events);
      if (this.elapsed >= scope.sampleRate * .032 || this.pending.length
          || (result.drained && !this.lastReportedDrain)) {
        this.port.postMessage({ type: 'progress', run_id: this.state.run_id, ...result,
          context_time_s: scope.currentTime, block_end_context_time_s: scope.currentTime + output.length / scope.sampleRate,
          device_rate: scope.sampleRate, events: this.pending });
        this.pending = []; this.elapsed = 0; this.lastReportedDrain = result.drained;
      }
      return true; // Main thread disconnects only after the queued tail reaches output.
    }
  }
  scope.registerProcessor('exp14-pcm-player', PCMPlayer);
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
function contextAnchor(context, now) {
  const performance_before_ms = now(), context_time_s = context.currentTime, performance_after_ms = now();
  return { context_time_s, performance_before_ms, performance_after_ms,
    uncertainty_ms: (performance_after_ms - performance_before_ms) / 2 + 128 / context.sampleRate * 1000,
    method: 'AudioContext.currentTime_bracketed_by_performance.now' };
}

// Web APIs are supplied at this boundary; importing/running the pure state in
// Node never opens a connection or an audio device.
export async function runBrowserTurn({ context, caseInfo, mode, onStatus = () => {} }, env = globalThis) {
  if (!['A', 'B', 'C'].includes(mode)) throw new Error('invalid mode');
  const now = () => env.performance.now();
  const id = `browser-${env.crypto.randomUUID()}`;
  const ledger = new OutputLedger(id), abort = new AbortController();
  const result = { id, session_id: id, turn_id: 1, generation_id: 1, case_id: caseInfo.id,
    mode, source: 'browser_web_audio',
    timestamps: { clock_domain: 'browser_performance', unit: 'ms',
      run_start_perf_ms: now(), input_start_perf_ms: null, input_end_perf_ms: null,
      input_reference_end_perf_ms: null, first_pcm_received_perf_ms: null,
      first_non_silent_render_perf_ms: null, first_non_silent_device_output_estimate_perf_ms: null,
      acoustic_first_sound_perf_ms: null, terminal_received_perf_ms: null, playback_drained_perf_ms: null },
    evidence: { input_frame_sends: [], input_events: [], output_frame_receipts: [], playback_events: [],
      ack_events: [], clock_anchors: [], output_timestamp_anchors: [], server_messages: [],
      dropped_late_frames: 0, input_complete: false, input_samples_sent: 0, output_samples_received: 0,
      output_samples_consumed: 0, playback_drained: false,
      queue_limit_source_samples: QUEUE_SAMPLES, device_sample_rate: context.sampleRate,
      silence: SILENCE, input_reference_mapping: null, input_manifest_case: caseInfo,
      get_output_timestamp_supported: typeof context.getOutputTimestamp === 'function',
      device_output_kind: 'estimate_not_acoustic', render_performance_kind: 'audio_context_sample_clock_calibration',
      server_clock_policy: 'preserve_server_monotonic_events_without_subtracting_browser_clock',
      ack_interval_ms: 32, underrun_rate: OUTPUT_RATE },
    underrun_samples: 0, underrun_events: 0, terminal: null, client_error: null };
  const evidence = result.evidence, times = result.timestamps;
  const terminalDone = deferred(), socketClosed = deferred(), drained = deferred();
  let socket, node, ackTimer, turnTimer, inputTask, hasReady = false, rendererEnded = false, finalized = false;
  let firstSoundContext = null, drainContext = null;
  const sleep = ms => new Promise(resolve => env.setTimeout(resolve, ms));
  const bounded = (promise, ms, message) => new Promise((resolve, reject) => {
    const timer = env.setTimeout(() => reject(new Error(message)), ms);
    promise.then(value => { env.clearTimeout(timer); resolve(value); }, error => { env.clearTimeout(timer); reject(error); });
  });
  const recordAnchor = () => {
    const anchor = contextAnchor(context, now); evidence.clock_anchors.push(anchor); return anchor;
  };
  const outputStamp = () => {
    if (!evidence.get_output_timestamp_supported) return null;
    try {
      const stamp = context.getOutputTimestamp();
      if (estimateOutputTime(context.currentTime, stamp) === null) return null;
      evidence.output_timestamp_anchors.push({ contextTime: stamp.contextTime,
        performanceTime: stamp.performanceTime, observed_performance_ms: now() });
      if (firstSoundContext !== null && times.first_non_silent_device_output_estimate_perf_ms === null) {
        times.first_non_silent_device_output_estimate_perf_ms = estimateOutputTime(firstSoundContext, stamp);
        evidence.first_sound_device_anchor_index = evidence.output_timestamp_anchors.length - 1;
      }
      return stamp;
    } catch (error) { evidence.output_timestamp_error = error.message; return null; }
  };
  const endRenderer = () => {
    if (node && !rendererEnded) {
      rendererEnded = true; node.port.postMessage({ type: 'terminal', run_id: id });
    }
  };
  const fail = message => {
    if (finalized) return;
    if (!result.client_error) result.client_error = String(message);
    abort.abort();
    if (socket?.readyState === 1 && !result.terminal) {
      try { socket.send(JSON.stringify({ type: 'cancel' })); } catch { /* close path records failure */ }
    }
    endRenderer();
  };
  const sendAck = () => {
    if (!hasReady || socket?.readyState !== 1 || result.terminal || result.client_error) return;
    const ack = ledger.ack(); socket.send(JSON.stringify(ack));
    evidence.ack_events.push({ ...ack, performance_ms: now(), received_samples: ledger.received });
  };
  try {
    onStatus(`${mode}：读取输入`);
    if (!/^[A-Za-z0-9_-]+\.wav$/.test(caseInfo.wav)) throw new Error('invalid WAV name');
    const response = await env.fetch(`/audio/${encodeURIComponent(caseInfo.wav)}`);
    if (!response.ok) throw new Error(`WAV HTTP ${response.status}`);
    const wav = await response.arrayBuffer(), { pcm } = parseWav(wav);
    if (caseInfo.samples !== pcm.length || caseInfo.sample_rate !== INPUT_RATE) throw new Error('WAV/manifest sample mismatch');
    const hash = await env.crypto.subtle.digest('SHA-256', wav);
    evidence.input_wav_sha256 = Array.from(new Uint8Array(hash), v => v.toString(16).padStart(2, '0')).join('');
    if (caseInfo.sha256 && evidence.input_wav_sha256 !== caseInfo.sha256) throw new Error('WAV SHA-256 mismatch');
    node = new env.AudioWorkletNode(context, 'exp14-pcm-player', { numberOfInputs: 0, numberOfOutputs: 1,
      outputChannelCount: [1], processorOptions: { run_id: id, turn_id: 1, generation_id: 1 } });
    node.port.onmessage = ({ data }) => {
      if (finalized || data.run_id !== id) { evidence.dropped_late_frames++; return; }
      try {
        if (data.type === 'error') { fail(data.message); return; }
        if (data.type !== 'progress' || !ledger.progress(data)) return;
        const observed_performance_ms = now(), anchor = recordAnchor();
        const anchor_index = evidence.clock_anchors.length - 1;
        evidence.output_samples_consumed = data.consumed_samples;
        result.underrun_samples = data.underrun_samples; result.underrun_events = data.underrun_events;
        evidence.underrun_device_frames = data.underrun_device_frames;
        evidence.playback_events.push({ type: 'playback_progress', context_time_s: data.context_time_s,
          block_end_context_time_s: data.block_end_context_time_s, observed_performance_ms, anchor_index,
          received_samples: data.received_samples, consumed_samples: data.consumed_samples,
          queued_samples: data.queued_samples, source_fraction: data.source_fraction,
          underrun_samples: data.underrun_samples, terminal: data.terminal, drained: data.drained });
        for (const event of data.events) {
          const performance_ms = mapContextToPerformance(event.context_time_s, anchor);
          evidence.playback_events.push({ ...event, performance_ms, observed_performance_ms, anchor_index });
          if (event.type === 'first_non_silent_render' && firstSoundContext === null) {
            firstSoundContext = event.context_time_s;
            times.first_non_silent_render_perf_ms = performance_ms;
            evidence.first_non_silent_source_sample = event.source_sample;
          } else if (event.type === 'playback_drained') {
            drainContext = event.context_time_s; times.playback_drained_perf_ms = performance_ms;
          }
        }
        outputStamp();
        if (data.drained) { sendAck(); drained.resolve(); }
      } catch (error) { fail(error.message); }
    };
    node.onprocessorerror = () => { fail('AudioWorklet processor error'); drained.resolve(); };
    recordAnchor(); node.connect(context.destination);
    const wsURL = new URL('/ws', env.location.href); wsURL.protocol = wsURL.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new env.WebSocket(wsURL.href); socket.binaryType = 'arraybuffer';
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'start', session_id: id, turn_id: 1, generation_id: 1, mode, playback: 'web_audio' }));
      evidence.input_events.push({ type: 'start_sent', performance_ms: now() });
    };
    socket.onmessage = ({ data }) => {
      if (finalized) { evidence.dropped_late_frames++; return; }
      try {
        const performance_ms = now();
        if (typeof data !== 'string') {
          if (!hasReady) throw new Error('audio before ready');
          if (result.terminal || result.client_error) { evidence.dropped_late_frames++; return; }
          const frame = ledger.accept(data);
          if (!frame) { evidence.dropped_late_frames++; return; }
          if (times.first_pcm_received_perf_ms === null) times.first_pcm_received_perf_ms = performance_ms;
          evidence.output_samples_received = ledger.received;
          evidence.output_frame_receipts.push({ seq: frame.seq, sample_offset: frame.sample_offset, count: frame.count, performance_ms });
          node.port.postMessage({ type: 'audio', run_id: id, packet: data }, [data]);
          return;
        }
        const message = JSON.parse(data);
        if ((message.session_id !== undefined && message.session_id !== id)
            || (message.turn_id !== undefined && message.turn_id !== 1)
            || (message.generation_id !== undefined && message.generation_id !== 1)) {
          evidence.dropped_late_frames++; return;
        }
        if (message.type === 'terminal') {
          if (result.terminal) throw new Error('duplicate terminal');
          result.terminal = message; times.terminal_received_perf_ms = performance_ms;
          if (Number.isInteger(message.output_samples) && message.output_samples !== ledger.received) fail('terminal output sample mismatch');
          if (!evidence.input_complete) abort.abort();
          endRenderer(); terminalDone.resolve();
        } else if (message.type === 'ready') {
          if (hasReady || message.input_rate !== INPUT_RATE || message.output_rate !== OUTPUT_RATE || message.format !== 'pcm16le') {
            throw new Error('invalid/duplicate ready format');
          }
          hasReady = true; evidence.server_messages.push({ message, performance_ms });
          onStatus(`${mode}：发送并播放`);
          inputTask = sendInput(pcm, { signal: abort.signal, now, sleep,
            send: data => { if (socket.readyState !== 1) throw new Error('input socket closed'); socket.send(data); },
            onEvent: event => {
              if (event.type === 'input_frame_sent') {
                evidence.input_frame_sends.push(event); evidence.input_samples_sent += event.count;
              } else evidence.input_events.push(event);
            } }).then(input => {
            times.input_start_perf_ms = input.input_start_perf_ms; times.input_end_perf_ms = input.input_end_perf_ms;
            evidence.input_complete = input.complete;
          }).catch(error => { if (!result.terminal) fail(error.message); });
        } else evidence.server_messages.push({ message, performance_ms });
      } catch (error) { fail(error.message); }
    };
    socket.onclose = event => {
      evidence.socket_close = { code: event.code, reason: event.reason, performance_ms: now() };
      if (!result.terminal) fail('socket closed without terminal');
      endRenderer(); terminalDone.resolve(); socketClosed.resolve();
    };
    socket.onerror = () => fail('WebSocket error');
    ackTimer = env.setInterval(() => {
      try { if (context.state !== 'running') fail('AudioContext suspended'); else sendAck(); }
      catch (error) { fail(error.message); }
    }, 32);
    turnTimer = env.setTimeout(() => {
      fail('browser turn timeout (45s)'); socket.close(); terminalDone.resolve(); socketClosed.resolve();
    }, 45000);
    await terminalDone.promise;
    await inputTask;
    if (result.terminal && ['stop', 'length'].includes(result.terminal.finish_reason)
        && (!evidence.input_complete || evidence.input_samples_sent !== pcm.length
          || result.terminal.input_complete !== true || result.terminal.input_samples !== pcm.length)) {
      fail('terminal input completeness mismatch');
    }
    await bounded(socketClosed.promise, 3000, 'socket did not close after terminal');
    await bounded(drained.promise, 3500, 'playback drain timeout');
    // Preserve the last quantum through the estimated output boundary before
    // disconnecting. Unsupported device timestamps remain null in the report.
    const stamp = outputStamp();
    const estimatedTail = drainContext === null ? null : estimateOutputTime(drainContext, stamp);
    const fallbackMs = Math.max(.1, (context.baseLatency || 0) + (context.outputLatency || 0)) * 1000;
    const tailWait = estimatedTail === null ? fallbackMs : Math.max(0, estimatedTail - now());
    if (tailWait > 3000) throw new Error('device output estimate outside drain budget');
    evidence.tail_wait = { method: estimatedTail === null ? 'latency_margin' : 'getOutputTimestamp_estimate',
      estimated_device_tail_perf_ms: estimatedTail, wait_ms: tailWait + 128 / context.sampleRate * 1000 };
    await sleep(evidence.tail_wait.wait_ms);
    outputStamp();
    evidence.playback_drained = drainContext !== null && ledger.consumed === ledger.received;
  } catch (error) { fail(error.message); }
  finally {
    finalized = true; abort.abort(); env.clearInterval(ackTimer); env.clearTimeout(turnTimer);
    if (inputTask) await inputTask;
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      if (socket.readyState < 2) socket.close();
    }
    if (node) { node.disconnect(); node.port.onmessage = null; node.port.close(); }
  }
  const frames = evidence.input_frame_sends;
  if (frames.length && times.input_start_perf_ms === null) times.input_start_perf_ms = frames[0].performance_ms;
  const intervals = caseInfo.speech_intervals;
  const reference = Array.isArray(intervals) && intervals.length
    && intervals.every(i => Number.isInteger(i.start) && Number.isInteger(i.end) && i.start >= 0
      && i.end > i.start && i.end <= caseInfo.samples) ? Math.max(...intervals.map(i => i.end)) : null;
  evidence.input_reference_mapping = referenceSampleMapping(reference, frames);
  evidence.input_reference_kind = 'offline_energy_envelope_not_human_or_acoustic';
  times.input_reference_end_perf_ms = evidence.input_reference_mapping?.performance_ms ?? null;
  const baseline = evidence.input_complete ? times.input_reference_end_perf_ms : null;
  const delta = value => baseline !== null && value !== null ? value - baseline : null;
  result.latencies_ms = { reference_to_first_pcm: delta(times.first_pcm_received_perf_ms),
    reference_to_first_render: delta(times.first_non_silent_render_perf_ms),
    reference_to_device_output_estimate: delta(times.first_non_silent_device_output_estimate_perf_ms) };
  if (!result.terminal) result.terminal = { type: 'client_terminal', finish_reason: 'missing_server_terminal' };
  evidence.server_terminal_received = result.terminal.type === 'terminal';
  times.run_end_perf_ms = now();
  onStatus(`${mode}：保存结果`);
  try {
    const saved = await env.fetch('/browser-result', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
    if (!saved.ok) throw new Error(`browser-result HTTP ${saved.status}`);
    const receipt = await saved.json();
    if (receipt.saved !== id) throw new Error('browser-result receipt mismatch');
    result.saved = true;
  } catch (error) { result.saved = false; result.save_error = error.message; }
  return result;
}

if (typeof globalThis.registerProcessor === 'function' && typeof globalThis.AudioWorkletProcessor === 'function') {
  registerPlaybackWorklet();
}
