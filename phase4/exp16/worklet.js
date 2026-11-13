/* Frame values are exclusive sample boundaries in the AudioContext clock.
 * played counts consumed PCM, including zero-valued samples, never underrun silence. */
class Exp16Playback extends AudioWorkletProcessor {
  constructor(options = {}) {
    super();
    const config = options.processorOptions || {};
    this.warmupQuanta = config.warmup_quanta ?? 8;
    this.quanta = 0;
    this.ready = false;
    this.quantumFrames = null;
    this.active = null;
    this.invalid = new Set();
    this.generations = {};
    this.queue = [];
    this.reportFrame = 0;
    this.defaultTrigger = config.trigger_samples ?? null;
    this.port.onmessage = ({ data }) => this.message(data);
  }

  state(generation) {
    if (!this.generations[generation]) this.generations[generation] = {
      generation, played: 0, accepted: 0, queued: 0, discarded: 0, next_offset: 0,
      rejected: 0, stale_rejected: 0, stale_accepted: 0, done: false, invalid: false,
      first_render_frame: null, last_render_end_frame: null, underrun_samples: 0,
      trigger_samples: null, triggered: false, empty_reported: false,
    };
    return this.generations[generation];
  }

  emit(type, fields = {}) {
    this.port.postMessage({ type, frame: currentFrame, currentFrame,
      quantum_frame: currentFrame, quantum_frames: this.quantumFrames,
      sample_rate: sampleRate, ...fields });
  }

  snapshot(type = 'snapshot', fields = {}) {
    const generations = {};
    for (const [key, value] of Object.entries(this.generations)) generations[key] = { ...value };
    this.emit(type, { active_generation: this.active, generations, ...fields });
  }

  reject(data, reason, fields = {}) {
    const stale = data.type === 'stale_probe' || data.stale_probe === true;
    if (data.generation === 1 || data.generation === 2) {
      const state = this.state(data.generation);
      state.rejected++;
      if (stale) state.stale_rejected++;
    }
    this.emit('rejected', { generation: data.generation, segment: data.segment,
      offset: data.offset, samples: data.samples?.length ?? 0,
      stale_probe: stale, probe_id: data.probe_id ?? null, reason, ...fields });
  }

  enqueue(data) {
    const generation = data.generation;
    // The fence precedes payload and offset validation, also for controlled probes.
    if (this.invalid.has(generation)) return this.reject(data, 'generation_fence');
    if (generation !== this.active || (generation !== 1 && generation !== 2))
      return this.reject(data, 'inactive_generation');
    const state = this.state(generation);
    if (!Number.isSafeInteger(data.offset) || data.offset !== state.next_offset)
      return this.reject(data, 'offset_mismatch', { expected_offset: state.next_offset });
    if (state.done) return this.reject(data, 'generation_done');
    let samples;
    try {
      samples = data.samples instanceof Float32Array ? data.samples
        : data.samples instanceof ArrayBuffer ? new Float32Array(data.samples) : null;
    } catch (_) { samples = null; }
    if (!Number.isSafeInteger(data.segment) || data.segment < 0 || !samples?.length ||
        !Number.isSafeInteger(data.offset + samples.length) ||
        !samples.every(value => Number.isFinite(value) && value >= -1 && value <= 1))
      return this.reject(data, 'invalid_payload');
    const stale = data.type === 'stale_probe' || data.stale_probe === true;
    this.queue.push({ generation, segment: data.segment, offset: data.offset, samples, position: 0 });
    state.next_offset += samples.length;
    state.accepted += samples.length;
    state.queued += samples.length;
    state.empty_reported = false;
    if (stale) state.stale_accepted++;
    this.emit('enqueued', { generation, segment: data.segment, offset: data.offset,
      samples: samples.length, queued: state.queued, next_offset: state.next_offset,
      stale_probe: stale, probe_id: data.probe_id ?? null });
  }

  empty(state, frame = currentFrame) {
    if (state.queued || state.empty_reported) return;
    state.empty_reported = true;
    this.emit('queueempty', { ...state, frame });
  }

  message(data) {
    if (!data || typeof data !== 'object') return;
    if (['enqueue', 'audio', 'pcm', 'stale_probe'].includes(data.type)) return this.enqueue(data);
    if (data.type === 'snapshot') return this.snapshot('snapshot', { request_id: data.request_id ?? null });
    const generation = data.generation;
    if (generation !== 1 && generation !== 2) return;
    const state = this.state(generation);
    if (data.type === 'activate') {
      if (this.invalid.has(generation))
        return this.emit('activation_rejected', { generation, reason: 'generation_fence' });
      const previous = this.active === null ? null : this.state(this.active);
      if (previous && this.active !== generation && !previous.invalid && (!previous.done || previous.queued))
        return this.emit('activation_rejected', { generation, reason: 'previous_generation_not_stopped' });
      this.active = generation;
      state.trigger_samples = generation === 1 ? (data.trigger_samples ?? this.defaultTrigger) : null;
      this.emit('activated', { generation, played: state.played });
    } else if (data.type === 'flush') {
      this.invalid.add(generation);
      state.invalid = true;
      const discarded = state.queued;
      this.queue = this.queue.filter(item => item.generation !== generation);
      state.discarded += discarded;
      state.queued = 0;
      state.empty_reported = true;
      this.emit('flush_ack', { ...state, discarded: state.discarded, discarded_now: discarded });
    } else if (data.type === 'generation_done' || data.type === 'done') {
      state.done = true;
      state.empty_reported = false;
      this.empty(state);
    }
  }

  process(_inputs, outputs) {
    const channels = outputs[0] || [];
    if (!channels.length) return true;
    const output = channels[0];
    this.quantumFrames = output.length;
    for (const channel of channels) channel.fill(0);
    if (!this.ready) {
      this.quanta++;
      if (this.quanta < this.warmupQuanta) return true;
      this.ready = true;
      this.emit('probe_ready', { warmup_quanta: this.quanta });
    }
    const state = this.active === null ? null : this.state(this.active);
    if (state && !state.invalid) {
      for (let i = 0; i < output.length; i++) {
        const item = this.queue[0];
        if (!item) {
          if (state.first_render_frame !== null && !state.done) state.underrun_samples++;
          continue;
        }
        output[i] = item.samples[item.position++];
        state.played++;
        state.queued--;
        if (state.first_render_frame === null) {
          state.first_render_frame = currentFrame + i;
          this.emit('first_render', { generation: this.active, played: state.played,
            frame: currentFrame + i, sample_frame: currentFrame + i });
        }
        state.last_render_end_frame = currentFrame + i + 1;
        if (!state.triggered && Number.isSafeInteger(state.trigger_samples) &&
            state.trigger_samples > 0 && state.played === state.trigger_samples) {
          state.triggered = true;
          this.emit('trigger', { generation: this.active, played: state.played,
            frame: currentFrame + i + 1, sample_frame: currentFrame + i + 1,
            offset_in_quantum: i + 1, segment: item.segment,
            stream_offset: item.offset + item.position });
        }
        if (item.position === item.samples.length) this.queue.shift();
      }
      this.empty(state, currentFrame + output.length);
    }
    for (let channel = 1; channel < channels.length; channel++) channels[channel].set(output);
    if (currentFrame - this.reportFrame >= sampleRate / 10) {
      this.reportFrame = currentFrame;
      this.snapshot('progress', { frame: currentFrame + output.length });
    }
    return true;
  }
}
registerProcessor('exp16-playback', Exp16Playback);
