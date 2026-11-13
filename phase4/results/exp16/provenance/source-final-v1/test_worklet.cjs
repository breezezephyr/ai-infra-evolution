'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function harness(options = {}) {
  const events = [];
  let Processor;
  const context = vm.createContext({
    currentFrame: 0, sampleRate: 24000, Float32Array, ArrayBuffer,
    AudioWorkletProcessor: class {
      constructor() { this.port = { postMessage: data => events.push(structuredClone(data)) }; }
    },
    registerProcessor(name, implementation) {
      assert.equal(name, 'exp16-playback'); Processor = implementation;
    },
  });
  const sourcePath = path.join(__dirname, 'worklet.js');
  assert.ok(fs.existsSync(sourcePath), 'the exp16 playback worklet must exist');
  vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  const processor = new Processor({ processorOptions: { warmup_quanta: 0, ...options } });
  const send = data => processor.port.onmessage({ data });
  const tick = (length = 128) => {
    const output = new Float32Array(length).fill(0.99);
    assert.equal(processor.process([], [[output]]), true);
    context.currentFrame += length;
    return output;
  };
  const last = type => events.filter(event => event.type === type).at(-1);
  const enqueue = (generation, offset, count, extra = {}) => send({
    type: 'enqueue', generation, segment: 0, offset,
    samples: new Float32Array(count).fill(generation / 4), ...extra,
  });
  tick();
  return { send, tick, last, events, enqueue, context };
}

test('probe_ready follows silent warmup and reports the real rate and quantum', () => {
  const h = harness({ warmup_quanta: 3 });
  assert.equal(h.last('probe_ready'), undefined);
  assert.ok(h.tick().every(sample => sample === 0));
  h.tick();
  assert.equal(h.last('probe_ready').sample_rate, 24000);
  assert.equal(h.last('probe_ready').quantum_frames, 128);
});

test('flush clears queued PCM and reports exactly what rendered and was discarded', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1, trigger_samples: 4800 });
  h.enqueue(1, 0, 500);
  h.tick();
  h.send({ type: 'flush', generation: 1 });
  const ack = h.last('flush_ack');
  assert.equal(ack.played, 128);
  assert.equal(ack.discarded, 372);
  assert.equal(ack.queued, 0);
  assert.equal(ack.last_render_end_frame, ack.frame);
  assert.ok(h.tick().every(sample => sample === 0));
  h.send({ type: 'snapshot' });
  assert.equal(h.last('snapshot').generations['1'].played, 128);
});

test('old generation and controlled stale probes hit the same fence before offset checks', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1 });
  h.enqueue(1, 0, 300);
  h.send({ type: 'flush', generation: 1 });
  h.enqueue(1, 300, 20);
  assert.equal(h.last('rejected').reason, 'generation_fence');
  h.enqueue(1, 0, 20, { type: 'stale_probe', probe_id: 'controlled' });
  assert.equal(h.last('rejected').reason, 'generation_fence');
  assert.equal(h.last('rejected').stale_probe, true);
  assert.equal(h.last('rejected').probe_id, 'controlled');
  assert.ok(h.tick().every(sample => sample === 0));
});

test('new generation requires activate and plays after a flush', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1 });
  h.send({ type: 'flush', generation: 1 });
  h.enqueue(2, 0, 128);
  assert.equal(h.last('rejected').reason, 'inactive_generation');
  h.send({ type: 'activate', generation: 2 });
  h.enqueue(2, 0, 128);
  assert.ok(h.tick().every(sample => sample === 0.5));
  h.send({ type: 'activate', generation: 1 });
  assert.equal(h.last('activation_rejected').reason, 'generation_fence');
});

test('offset gaps and duplicates are rejected without altering the next offset', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1 });
  h.enqueue(1, 5, 32);
  assert.equal(h.last('rejected').expected_offset, 0);
  h.enqueue(1, 0, 32);
  h.enqueue(1, 0, 32, { type: 'stale_probe' });
  assert.equal(h.last('rejected').reason, 'offset_mismatch');
  assert.equal(h.last('rejected').expected_offset, 32);
  h.enqueue(1, 32, 32);
  h.send({ type: 'snapshot' });
  assert.equal(h.last('snapshot').generations['1'].accepted, 64);
  assert.equal(h.last('snapshot').generations['1'].next_offset, 64);
});

test('natural tail is zero filled and queueempty carries the last exact render boundary', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1 });
  h.enqueue(1, 0, 131);
  h.send({ type: 'generation_done', generation: 1 });
  h.tick();
  const lastBlockStart = h.context.currentFrame;
  const output = h.tick();
  assert.deepEqual(Array.from(output.slice(0, 3)), [0.25, 0.25, 0.25]);
  assert.ok(output.slice(3).every(sample => sample === 0));
  assert.equal(h.last('queueempty').played, 131);
  assert.equal(h.last('queueempty').last_render_end_frame, lastBlockStart + 3);
  assert.equal(h.last('queueempty').done, true);
});

test('a terminal arriving after an empty quantum still emits a terminal queueempty', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 2 });
  h.enqueue(2, 0, 10);
  h.tick();
  assert.equal(h.last('queueempty').done, false);
  h.send({ type: 'generation_done', generation: 2 });
  assert.equal(h.last('queueempty').done, true);
  assert.equal(h.last('queueempty').played, 10);
});

for (const trigger of [4800, 24000, 96000]) {
  test(`trigger ${trigger} records the precise sample inside a render quantum`, () => {
    const h = harness();
    h.send({ type: 'activate', generation: 1, trigger_samples: trigger });
    h.enqueue(1, 0, trigger + 256);
    const firstFrame = h.context.currentFrame;
    for (let i = 0; i < Math.ceil(trigger / 128); i++) h.tick();
    const event = h.last('trigger');
    assert.equal(event.played, trigger);
    assert.equal(event.frame, firstFrame + trigger);
    assert.equal(event.currentFrame, event.quantum_frame);
    assert.equal(event.frame, event.quantum_frame + event.offset_in_quantum);
    assert.equal(h.events.filter(item => item.type === 'trigger').length, 1);
  });
}

test('starvation before the trigger does not advance played or shift its sample count', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1, trigger_samples: 150 });
  h.enqueue(1, 0, 100);
  h.tick(); h.tick();
  assert.equal(h.last('trigger'), undefined);
  h.enqueue(1, 100, 100);
  const resumedFrame = h.context.currentFrame;
  h.tick();
  assert.equal(h.last('trigger').played, 150);
  assert.equal(h.last('trigger').frame, resumedFrame + 50);
});

test('invalid payloads and unsafe activation cannot destroy queued audio', () => {
  const h = harness();
  h.send({ type: 'activate', generation: 1 });
  h.enqueue(1, 0, 128);
  h.send({ type: 'activate', generation: 2 });
  assert.equal(h.last('activation_rejected').reason, 'previous_generation_not_stopped');
  h.enqueue(1, 128, 1, { samples: new Float32Array([NaN]) });
  assert.equal(h.last('rejected').reason, 'invalid_payload');
  assert.ok(h.tick().every(sample => sample === 0.25));
});
