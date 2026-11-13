import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

// A missing implementation is an assertion failure in the initial RED run.
let api = {};
try { api = await import('./playback.js'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }
function feature(name) {
  assert.equal(typeof api[name], 'function', `${name} 尚未实现`);
  return api[name];
}
function player(options = {}) {
  const State = feature('PlaybackState');
  return new State({ run_id: 'current', device_rate: 48000, ...options });
}
function packet(pcm, seq = 0, offset = 0, turn = 1, generation = 1) {
  return feature('packAudio')({ turn_id: turn, generation_id: generation,
    seq, sample_offset: offset, pcm: Int16Array.from(pcm) });
}
function near(actual, expected, tolerance = 1e-7) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
}
function wav(values, { rate = 16000, channels = 1, bits = 16, format = 1 } = {}) {
  // Odd-sized JUNK chunk exercises RIFF padding and non-44-byte data offsets.
  const b = Buffer.alloc(56 + values.length * 2);
  b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVE', 8);
  b.write('JUNK', 12); b.writeUInt32LE(3, 16); b.write('abc', 20);
  b.write('fmt ', 24); b.writeUInt32LE(16, 28); b.writeUInt16LE(format, 32);
  b.writeUInt16LE(channels, 34); b.writeUInt32LE(rate, 36);
  b.writeUInt32LE(rate * channels * bits / 8, 40);
  b.writeUInt16LE(channels * bits / 8, 44); b.writeUInt16LE(bits, 46);
  b.write('data', 48); b.writeUInt32LE(values.length * 2, 52);
  values.forEach((value, i) => b.writeInt16LE(value, 56 + i * 2));
  return b;
}

test('WAV DataView reads exact signed 16 kHz samples through padded chunks', () => {
  const result = feature('parseWav')(wav([-32768, -120, 0, 32767]));
  assert.equal(result.sample_rate, 16000);
  assert.deepEqual([...result.pcm], [-32768, -120, 0, 32767]);
});
test('WAV rejects resampled formats, inconsistent lengths and half samples', () => {
  const parse = feature('parseWav');
  for (const options of [{ rate: 24000 }, { channels: 2 }, { bits: 8 }, { format: 3 }]) {
    assert.throws(() => parse(wav([1, 2], options)));
  }
  assert.throws(() => parse(wav([1, 2]).subarray(0, 59)));
  const odd = wav([1, 2]); odd.writeUInt32LE(3, 52);
  assert.throws(() => parse(odd));
});
test('wire format matches the 28-byte <4sIIIQI little-endian header', () => {
  const bytes = packet([-32768, 32767], 7, 2 ** 32 + 9, 3, 4);
  assert.equal(Buffer.from(bytes).toString('hex'),
    '503441310300000004000000070000000900000001000000020000000080ff7f');
  const frame = feature('unpackAudio')(bytes);
  assert.equal(frame.sample_offset, 4294967305);
  assert.deepEqual([...frame.pcm], [-32768, 32767]);
});
test('wire decoder rejects truncated, excess, empty and oversized payloads', () => {
  const decode = feature('unpackAudio');
  const b = Buffer.from(packet([1, 2]));
  for (const invalid of [b.subarray(0, 27), b.subarray(0, 31), Buffer.concat([b, Buffer.from([0])])]) {
    assert.throws(() => decode(invalid));
  }
  const badMagic = Buffer.from(b); badMagic[0] = 0; assert.throws(() => decode(badMagic));
  assert.throws(() => packet([]));
  assert.throws(() => packet(new Int16Array(3201)));
});
test('sequence and sample offsets start at zero and reject gaps without advancing', () => {
  const p = player();
  assert.throws(() => p.enqueue(packet([100], 1, 0)));
  assert.throws(() => p.enqueue(packet([100], 0, 1)));
  assert.equal(p.enqueue(packet([100, 200])), true);
  assert.throws(() => p.enqueue(packet([300], 0, 2)));
  assert.equal(p.enqueue(packet([300], 1, 2)), true);
  assert.equal(p.snapshot().received_samples, 3);
});
test('old turn, generation and previous session frames cannot contaminate playback', () => {
  const p = player({ turn_id: 2, generation_id: 3 });
  assert.equal(p.enqueue(packet([999], 99, 999, 1, 9)), false);
  assert.equal(p.enqueue(packet([999], 99, 999, 2, 2)), false);
  assert.equal(p.enqueue(packet([999], 0, 0, 2, 3), 'previous'), false);
  assert.equal(p.markTerminal('previous'), false);
  assert.throws(() => p.enqueue(packet([999], 0, 0, 3, 1)));
  assert.equal(p.enqueue(packet([200], 0, 0, 2, 3)), true);
  assert.equal(p.snapshot().received_samples, 1);
  assert.equal(p.snapshot().terminal, false);
});
test('queue accepts exactly 48000 source samples and rejects overflow atomically', () => {
  const p = player();
  for (let i = 0; i < 15; i++) p.enqueue(packet(new Int16Array(3200), i, i * 3200));
  assert.throws(() => p.enqueue(packet([1], 15, 48000)), /queue/i);
  assert.equal(p.snapshot().queued_samples, 48000);
  p.render(new Float32Array(960), 0);
  p.enqueue(packet(new Int16Array(480), 15, 48000));
  assert.equal(p.snapshot().received_samples, 48480);
});
test('24k to 48k interpolation spans packet boundaries and terminal drains the tail', () => {
  const p = player();
  p.enqueue(packet([0, 8192])); p.enqueue(packet([16384, 24576], 1, 2));
  p.markTerminal();
  const out = new Float32Array(8); const result = p.render(out, 1);
  assert.deepEqual([...out], [0, .125, .25, .375, .5, .625, .75, .75]);
  assert.equal(result.consumed_samples, 4);
  assert.equal(result.drained, true); assert.equal(result.underrun_samples, 0);
});
test('fractional resampling at 44100 Hz preserves source position across render blocks', () => {
  const p = player({ device_rate: 44100 });
  p.enqueue(packet(Array.from({ length: 240 }, (_, i) => i * 100)));
  p.markTerminal();
  const a = new Float32Array(101), b = new Float32Array(340);
  p.render(a, 0); const end = p.render(b, 101 / 44100);
  near(a[1], (100 / 32768) * 80 / 147);
  near(b[0], (101 * 80 / 147 * 100) / 32768);
  assert.equal(end.consumed_samples, 240); assert.equal(end.drained, true);
});
test('downsampling consumes skipped source samples and never acknowledges unreceived samples', () => {
  const p = player({ device_rate: 16000 });
  p.enqueue(packet([0, 8192, 16384])); p.markTerminal();
  const out = new Float32Array(8); const result = p.render(out, 0);
  assert.deepEqual([...out], [0, .375, 0, 0, 0, 0, 0, 0]);
  assert.equal(result.consumed_samples, 3); assert.equal(result.queued_samples, 0);
});
test('initial wait and time after terminal drain are excluded from underrun', () => {
  const p = player();
  assert.equal(p.render(new Float32Array(9600), 0).underrun_samples, 0);
  p.enqueue(packet([1000, 1000])); p.markTerminal();
  const end = p.render(new Float32Array(9600), 1);
  assert.equal(end.underrun_samples, 0); assert.equal(end.drained, true);
  assert.equal(p.render(new Float32Array(9600), 2).underrun_samples, 0);
});
test('active starvation counts only missing source time and stops at terminal even when empty', () => {
  const p = player();
  p.enqueue(packet([1000, 1000]));
  const first = p.render(new Float32Array(8), 0);
  assert.equal(first.consumed_samples, 1); // Fractional tail awaits a lookahead sample.
  assert.equal(first.underrun_samples, 2); // Five missing 48k device samples = 2.5 at 24k.
  assert.equal(first.underrun_events, 1);
  p.markTerminal();
  const end = p.render(new Float32Array(100), 8 / 48000);
  assert.equal(end.consumed_samples, 2); assert.equal(end.underrun_samples, 2);
  assert.equal(end.drained, true);
});
test('queue starvation resumes continuously without losing a fractional tail or inventing acks', () => {
  const p = player(); p.enqueue(packet([0, 8192]));
  p.render(new Float32Array(10), 0);
  p.enqueue(packet([16384, 24576], 1, 2)); p.markTerminal();
  const out = new Float32Array(5); const s = p.render(out, 10 / 48000);
  assert.deepEqual([...out], [.375, .5, .625, .75, .75]);
  assert.equal(s.consumed_samples, 4); assert.equal(s.drained, true);
});
test('terminal without any audio drains immediately and rejects subsequent current frames', () => {
  const p = player(); p.markTerminal();
  assert.equal(p.snapshot().drained, true);
  assert.equal(p.render(new Float32Array(128), 0).underrun_samples, 0);
  assert.throws(() => p.enqueue(packet([1])), /terminal/i);
});
test('silence uses fixed 10ms RMS windows and records the first qualifying rendered sample', () => {
  const p = player();
  p.enqueue(packet([...new Int16Array(240), ...new Int16Array(240).fill(119),
    ...new Int16Array(240).fill(120)]));
  p.markTerminal();
  const s = p.render(new Float32Array(1440), 3);
  const first = s.events.find(e => e.type === 'first_non_silent_render');
  assert.ok(first); near(first.context_time_s, 3.02); near(first.source_sample, 480);
  assert.ok(s.events.some(e => e.type === 'first_pcm_render' && e.context_time_s === 3));
});
test('one loud impulse below window RMS threshold does not become first sound', () => {
  const p = player({ device_rate: 24000 });
  const pcm = new Int16Array(240); pcm[17] = 121;
  p.enqueue(packet(pcm)); p.markTerminal();
  const s = p.render(new Float32Array(240), 0);
  assert.equal(s.events.some(e => e.type === 'first_non_silent_render'), false);
});
test('terminal evaluates a partial final silence window rather than losing a short sound', () => {
  const p = player(); p.enqueue(packet([200, 200])); p.markTerminal();
  const s = p.render(new Float32Array(128), 2);
  near(s.events.find(e => e.type === 'first_non_silent_render').context_time_s, 2);
});
test('device output estimate uses getOutputTimestamp clock mapping and unsupported maps to null', () => {
  const estimate = feature('estimateOutputTime');
  assert.equal(estimate(2.5, { contextTime: 2, performanceTime: 1000 }), 1500);
  for (const stamp of [null, {}, { contextTime: 0, performanceTime: 0 },
    { contextTime: NaN, performanceTime: 1000 }]) assert.equal(estimate(2.5, stamp), null);
  const map = feature('mapContextToPerformance');
  assert.equal(map(2.5, { context_time_s: 2, performance_before_ms: 990,
    performance_after_ms: 1010 }), 1500);
  assert.equal(map(2.5, null), null);
});
test('reference end maps within the actual frame send, including an exact frame boundary', () => {
  const map = feature('referenceSampleMapping');
  const frames = [{ sample_offset: 0, count: 320, performance_ms: 100 },
    { sample_offset: 320, count: 320, performance_ms: 127 }];
  assert.equal(map(480, frames).performance_ms, 137);
  assert.equal(map(320, frames).performance_ms, 120);
  assert.equal(map(0, frames).performance_ms, 100);
  assert.equal(map(641, frames), null); assert.equal(map(null, frames), null);
});
test('input replay uses 320 sample packets at real 20ms cadence and waits for the final tail', async () => {
  const sendInput = feature('sendInput');
  let time = 100;
  const sent = [];
  const result = await sendInput(new Int16Array(650), {
    now: () => time, sleep: async ms => { time += ms; },
    send: data => sent.push({ time, data }),
  });
  assert.deepEqual(sent.map(e => e.time), [100, 120, 140, 140.625]);
  assert.deepEqual(sent.slice(0, 3).map(e => feature('unpackAudio')(e.data).sample_offset), [0, 320, 640]);
  assert.equal(JSON.parse(sent[3].data).type, 'input_end');
  assert.equal(result.sent_samples, 650); assert.equal(result.complete, true);
});
test('late input timers do not catch up by bursting multiple packets together', async () => {
  const sendInput = feature('sendInput');
  let time = 0, delayed = false; const sends = [];
  await sendInput(new Int16Array(960), {
    now: () => time,
    sleep: async ms => { time += ms + (delayed ? 0 : 70); delayed = true; },
    send: data => { if (typeof data !== 'string') sends.push(time); },
  });
  assert.deepEqual(sends, [0, 90, 110]);
});
test('abort stops input without an input_end that falsely claims full delivery', async () => {
  const sendInput = feature('sendInput');
  const controller = new AbortController(); let time = 0; const sent = [];
  await assert.rejects(sendInput(new Int16Array(640), {
    signal: controller.signal, now: () => time,
    sleep: async ms => { time += ms; controller.abort(); }, send: data => sent.push(data),
  }), /abort/i);
  assert.equal(sent.length, 1);
});
test('real worklet adapter filters old messages and reports actual consumption with a bounded cadence', () => {
  let Processor; let contextTime = 0; const messages = [];
  class Base { constructor() { this.port = { postMessage: m => messages.push(m) }; } }
  feature('registerPlaybackWorklet')({ AudioWorkletProcessor: Base, sampleRate: 48000,
    get currentTime() { return contextTime; },
    registerProcessor: (_name, Type) => { Processor = Type; } });
  const p = new Processor({ processorOptions: { run_id: 'current' } });
  p.port.onmessage({ data: { type: 'audio', run_id: 'old', packet: packet([999]) } });
  p.process([], [[new Float32Array(128)]]);
  p.port.onmessage({ data: { type: 'audio', run_id: 'current',
    packet: packet(new Int16Array(2400).fill(1000)) } });
  for (let i = 0; i < 24; i++) {
    contextTime = (i + 1) * 128 / 48000; p.process([], [[new Float32Array(128)]]);
  }
  const progress = messages.filter(m => m.type === 'progress');
  assert.ok(progress.length >= 2 && progress.length <= 6);
  assert.ok(progress.every(m => m.run_id === 'current' && m.consumed_samples <= 2400));
  assert.ok(progress.at(-1).consumed_samples > 1000);
});

test('main-thread ledger acknowledges consumed source samples, never receipt or fractional progress', () => {
  const Ledger = feature('OutputLedger'); const ledger = new Ledger('current');
  ledger.accept(packet([1, 2, 3, 4]));
  assert.deepEqual(ledger.ack(), { type: 'ack', samples: 0 });
  ledger.progress({ run_id: 'current', consumed_samples: 2, received_samples: 4 });
  assert.deepEqual(ledger.ack(), { type: 'ack', samples: 2 });
  for (const consumed_samples of [1, 2.5, 5]) {
    assert.throws(() => ledger.progress({ run_id: 'current', consumed_samples, received_samples: 4 }));
  }
  assert.equal(ledger.progress({ run_id: 'previous', consumed_samples: 999 }), false);
  assert.deepEqual(ledger.ack(), { type: 'ack', samples: 2 });
});
test('main-thread ledger bounds in-flight plus worklet queue and drops stale socket identities', () => {
  const Ledger = feature('OutputLedger'); const ledger = new Ledger('current');
  assert.equal(ledger.accept(packet([1]), 'previous'), null);
  assert.equal(ledger.accept(packet([1], 999, 999, 0, 1)), null);
  for (let i = 0; i < 15; i++) ledger.accept(packet(new Int16Array(3200), i, i * 3200));
  assert.throws(() => ledger.accept(packet([1], 15, 48000)), /queue/i);
  ledger.progress({ run_id: 'current', consumed_samples: 1, received_samples: 48000 });
  ledger.accept(packet([1], 15, 48000));
  assert.equal(ledger.received, 48001);
});

test('an empty active queue counts starvation until terminal and none afterwards', () => {
  const p = player({ device_rate: 24000 }); p.enqueue(packet([1000, 1000]));
  assert.equal(p.render(new Float32Array(12), 0).underrun_samples, 10);
  p.markTerminal();
  assert.equal(p.render(new Float32Array(120), .001).underrun_samples, 10);
});

// Only the Web API boundary is replaced. Every worklet render, packet, timer,
// replay, ack and result payload below executes the real production functions.
async function controlledTurn({ deviceTimestamp = true, disconnect = false, saveFailure = false,
  earlyTerminal = false, terminalDelay = 0 } = {}) {
  const run = feature('runBrowserTurn');
  let clock = 1000, nextId = 1, activeNode, activeSocket, savedBody;
  const tasks = new Map(), sends = [], disconnectedAt = [];
  function schedule(fn, delay, interval = null) {
    const id = nextId++; tasks.set(id, { id, fn, at: clock + delay, interval }); return id;
  }
  const later = (fn, delay = 0) => schedule(fn, delay);
  const context = { state: 'running', sampleRate: 48000, baseLatency: .01, outputLatency: .02,
    destination: {}, get currentTime() { return clock / 1000; } };
  if (deviceTimestamp) context.getOutputTimestamp = () => ({ contextTime: (clock - 30) / 1000, performanceTime: clock });
  let Processor;
  class Base { constructor() { this.port = { postMessage: data => later(() => activeNode?.port.onmessage?.({ data })) }; } }
  feature('registerPlaybackWorklet')({ AudioWorkletProcessor: Base, sampleRate: 48000,
    get currentTime() { return clock / 1000; }, registerProcessor: (_name, Type) => { Processor = Type; } });
  class WorkletNode {
    constructor(_context, _name, options) {
      activeNode = this; this.worker = new Processor(options);
      this.port = { postMessage: data => later(() => this.worker.port.onmessage({ data })), close() {} };
    }
    connect() { this.timer = schedule(() => this.worker.process([], [[new Float32Array(128)]]), 128 / 48, 128 / 48); }
    disconnect() { disconnectedAt.push({ time: clock, consumed: this.worker.state.consumed }); tasks.delete(this.timer); }
  }
  const rawWav = wav(new Int16Array(650));
  const wavBuffer = rawWav.buffer.slice(rawWav.byteOffset, rawWav.byteOffset + rawWav.byteLength);
  let session;
  class Socket {
    constructor(url) {
      assert.equal(url, 'ws://example.invalid/ws'); activeSocket = this; this.readyState = 0;
      later(() => { this.readyState = 1; this.onopen?.(); });
    }
    send(data) {
      if (typeof data !== 'string') { sends.push({ time: clock, frame: api.unpackAudio(data) }); return; }
      const message = JSON.parse(data);
      sends.push({ time: clock, message, actual_consumed: activeNode.worker.state.consumed });
      if (message.type === 'start') {
        assert.equal(message.playback, 'web_audio'); session = message.session_id;
        later(() => this.onmessage?.({ data: JSON.stringify({ type: 'ready', input_rate: 16000,
          output_rate: 24000, format: 'pcm16le', max_output_buffer_samples: 48000 }) }));
        if (earlyTerminal) {
          later(() => this.onmessage?.({ data: JSON.stringify({ type: 'terminal', session_id: session,
            turn_id: 1, generation_id: 1, finish_reason: 'stop', output_samples: 0,
            input_samples: 0, input_complete: false }) }));
          later(() => this.close());
        }
      } else if (message.type === 'input_end') {
        later(() => this.onmessage?.({ data: packet(new Int16Array(960).fill(1000)) }));
        if (!disconnect) later(() => this.onmessage?.({ data: JSON.stringify({ type: 'terminal',
          session_id: session, turn_id: 1, generation_id: 1, finish_reason: 'stop', output_samples: 960,
          input_samples: 650, input_complete: true,
          events: [{ event: 'turn_terminal', clock_domain: 'server_monotonic', monotonic_ns: 900000000000000 }] }) }), terminalDelay);
        later(() => this.close(), terminalDelay);
      }
    }
    close() {
      if (this.readyState === 3) return;
      this.readyState = 3; later(() => this.onclose?.({ code: 1000, reason: '' }));
    }
  }
  const env = { performance: { now: () => clock }, location: { href: 'http://example.invalid/' },
    crypto: { randomUUID: () => 'controlled-0001', subtle: { digest: async (_name, bytes) => createHash('sha256').update(new Uint8Array(bytes)).digest() } },
    setTimeout: later, clearTimeout: id => tasks.delete(id),
    setInterval: (fn, delay) => schedule(fn, delay, delay), clearInterval: id => tasks.delete(id),
    WebSocket: Socket, AudioWorkletNode: WorkletNode,
    fetch: async (url, options) => {
      if (url === '/audio/short_01.wav') return { ok: true, arrayBuffer: async () => wavBuffer };
      assert.equal(url, '/browser-result'); assert.equal(options.method, 'POST');
      savedBody = JSON.parse(options.body);
      return { ok: !saveFailure, status: saveFailure ? 503 : 200, json: async () => ({ saved: savedBody.id }) };
    } };
  let result, error, settled = false;
  run({ context, mode: 'C', caseInfo: { id: 'short_01', wav: 'short_01.wav', samples: 650,
    sample_rate: 16000, speech_intervals: [{ start: 0, end: 320 }] } }, env)
    .then(value => { result = value; settled = true; }, value => { error = value; settled = true; });
  for (let i = 0; !settled && i < 2000; i++) {
    await new Promise(resolve => setImmediate(resolve));
    if (!tasks.size) continue;
    const task = [...tasks.values()].sort((a, b) => a.at - b.at || a.id - b.id)[0];
    tasks.delete(task.id); clock = task.at;
    if (task.interval !== null) tasks.set(task.id, { ...task, at: task.at + task.interval });
    task.fn();
  }
  assert.equal(settled, true, 'controlled turn did not settle'); if (error) throw error;
  return { result, savedBody, sends, disconnectedAt, socket: activeSocket };
}
test('browser turn sends start/input/actual acks and POSTs only after terminal audio tail is rendered', async () => {
  const { result, savedBody, sends, disconnectedAt } = await controlledTurn();
  assert.equal(result.client_error, null); assert.equal(result.saved, true);
  assert.equal(savedBody.source, 'browser_web_audio'); assert.equal(savedBody.id, result.id);
  assert.equal(savedBody.evidence.input_samples_sent, 650); assert.equal(savedBody.evidence.input_complete, true);
  assert.equal(savedBody.evidence.output_samples_consumed, 960); assert.equal(savedBody.evidence.playback_drained, true);
  assert.equal(savedBody.underrun_samples, 0); assert.equal(disconnectedAt[0].consumed, 960);
  const acks = sends.filter(s => s.message?.type === 'ack');
  assert.ok(acks.length); assert.ok(acks.every(s => s.message.samples <= s.actual_consumed));
  assert.ok(result.timestamps.first_non_silent_render_perf_ms >= result.timestamps.first_pcm_received_perf_ms);
  near(result.timestamps.first_non_silent_device_output_estimate_perf_ms - result.timestamps.first_non_silent_render_perf_ms, 30, 1e-6);
  assert.equal(result.timestamps.acoustic_first_sound_perf_ms, null);
  assert.equal(result.terminal.events[0].monotonic_ns, 900000000000000);
  assert.ok(result.latencies_ms.reference_to_first_render < 100);
});
test('unsupported output timestamp preserves null while render and input sample mappings remain recorded', async () => {
  const { result } = await controlledTurn({ deviceTimestamp: false });
  assert.equal(result.evidence.get_output_timestamp_supported, false);
  assert.equal(result.timestamps.first_non_silent_device_output_estimate_perf_ms, null);
  assert.equal(result.latencies_ms.reference_to_device_output_estimate, null);
  assert.ok(Number.isFinite(result.timestamps.first_non_silent_render_perf_ms));
  assert.equal(result.evidence.input_reference_mapping.reference_sample, 320);
});
test('socket close is a failure without explicit terminal but accepted output still drains', async () => {
  const { result } = await controlledTurn({ disconnect: true });
  assert.equal(result.terminal.finish_reason, 'missing_server_terminal');
  assert.match(result.client_error, /without terminal/);
  assert.equal(result.evidence.server_terminal_received, false);
  assert.equal(result.evidence.output_samples_consumed, 960); assert.equal(result.saved, true);
});
test('failed POST remains a visible failure with the full result available to download', async () => {
  const { result } = await controlledTurn({ saveFailure: true });
  assert.equal(result.saved, false); assert.match(result.save_error, /503/);
  assert.equal(result.evidence.output_samples_consumed, 960);
});
test('acks advance while streaming only after the real worklet consumes source samples', async () => {
  const { sends, result } = await controlledTurn({ terminalDelay: 30 });
  const acks = sends.filter(s => s.message?.type === 'ack');
  assert.ok(acks.some(s => s.message.samples > 0));
  assert.ok(acks.every(s => s.message.samples <= s.actual_consumed));
  assert.equal(result.client_error, null); assert.equal(result.underrun_samples, 0);
});
test('a premature success terminal cannot hide partial input as a successful complete run', async () => {
  const { result } = await controlledTurn({ earlyTerminal: true });
  assert.equal(result.evidence.input_complete, false);
  assert.match(result.client_error, /input/i);
  assert.equal(result.latencies_ms.reference_to_first_pcm, null);
});
