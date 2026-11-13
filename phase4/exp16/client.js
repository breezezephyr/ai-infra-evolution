'use strict';
(() => {
  const RATE = 24000;
  const $ = selector => document.querySelector(selector);
  let active = false;
  function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    promise.catch(() => {});
    return { promise, resolve, reject };
  }
  function decodePCM(pcm) {
    if (typeof pcm !== 'string') throw new Error('audio pcm must be base64 PCM16LE');
    const raw = atob(pcm);
    if (!raw.length || raw.length % 2) throw new Error('invalid PCM16 byte count');
    const samples = new Float32Array(raw.length / 2);
    for (let i = 0; i < samples.length; i++) {
      let value = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
      if (value & 0x8000) value -= 65536;
      samples[i] = value / 32768;
    }
    return samples;
  }
  function show(record) {
    if ($('#status')) $('#status').textContent = `${record.run_id}: ${record.outcome}`;
    if ($('#record')) $('#record').textContent = JSON.stringify(record, null, 2);
    const body = $('#results');
    if (!body) return;
    const row = body.insertRow();
    for (const value of [record.policy, record.trigger_samples, record.outcome,
      record.generations?.[1]?.played ?? '—', record.generations?.[2]?.played ?? '—',
      record.trigger_to_last_old_render_ms?.toFixed(3) ?? '—',
      record.trigger_notification_to_flush_ack_notification_ms?.toFixed(3) ?? '—',
      record.stale_rejection_count ?? 0]) row.insertCell().textContent = String(value);
  }

  window.runExp16 = async function runExp16({ policy = 'full', trigger_samples = 4800,
    run_id = `exp16-${policy}-${trigger_samples}-${Date.now()}`, timeout_ms = 90000 } = {}) {
    if (active) throw new Error('one active exp16 run only');
    if (!['full', 'server_only'].includes(policy) || ![4800, 24000, 96000].includes(trigger_samples))
      throw new Error('invalid policy or trigger_samples');
    if (!/^[A-Za-z0-9_.-]{1,100}$/.test(run_id)) throw new Error('invalid run_id');
    active = true;
    const record = {
      run_id, policy, trigger_samples, browser: navigator.userAgent, started_at: new Date().toISOString(),
      requested_sample_rate: RATE, context_rate: null, quantum_frames: null,
      scope: 'AudioWorklet PCM render consumption; no acoustic loopback or listening-quality claim',
      audio_frame_convention: 'trigger and last_render_end_frame are exclusive sample boundaries in one AudioContext clock',
      events: [], acks: [], segments: [], history: [], server_messages: [], generations: {},
      ignored_controlled_probe: 0, stale_rejection_count: 0, stale_fence_rejection_count: 0,
      validation_errors: [], error: null, outcome: 'running',
    };
    for (const generation of [1, 2]) record.generations[generation] = {
      generation, received_samples: 0, received_frames: 0, sent: null,
      controlled_probe_samples: 0, controlled_probe_frames: 0,
      played: 0, accepted: 0, queued: 0, discarded: 0, rejected: 0,
    };
    let ctx, silence, node, ws, ackTimer, deadlineTimer, finishedSeen = false;
    let resultSent = false, cancelled = false, nextStarted = false, flushPlayed = null, cleaningUp = false;
    window.exp16LastRecord = record;
    const fatal = deferred(), ready = deferred(), probe = deferred(), complete = deferred(), finished = deferred();
    const activated = new Map(), snapshots = new Map();
    const serverDone = new Set(), workersJoined = new Set(), stopped = new Set();
    let requestSequence = 0;
    const event = (name, data = {}, source = 'client') => {
      const value = { ...data, event: name, source, performance_ms: performance.now(),
        context_time: ctx?.currentTime ?? null };
      record.events.push(value);
      return value;
    };
    const fail = error => fatal.reject(error instanceof Error ? error : new Error(String(error)));
    const guard = promise => Promise.race([promise, fatal.promise]);
    function send(message) {
      if (!ws || ws.readyState !== WebSocket.OPEN) throw new Error(`WS not open for ${message.type}`);
      ws.send(JSON.stringify(message));
      event(`${message.type}_sent`, message.type === 'client_result' ? {} : message);
    }
    function merge(generation, data) {
      const target = record.generations[generation];
      if (!target) throw new Error(`invalid generation ${generation}`);
      if (data.played !== undefined && data.played < target.played) throw new Error('played regressed');
      Object.assign(target, data);
      if (generation === 1 && flushPlayed !== null && target.played !== flushPlayed)
        throw new Error('generation 1 consumed PCM after flush');
    }
    function ack(generation, played) {
      if (!serverDone.has(generation) && !record.generations[generation].activated) return;
      send({ type: 'ack', generation, played });
      record.acks.push({ generation, played, performance_ms: performance.now(),
        after_flush: generation === 1 && flushPlayed !== null });
    }
    function playbackStopped(generation, data, reason) {
      if (stopped.has(generation)) return;
      stopped.add(generation);
      merge(generation, data);
      record.generations[generation].playback_stop_reason = reason;
      ack(generation, data.played);
      send({ type: 'playback_stopped', generation, played: data.played });
      event('playback_stopped', { generation, played: data.played, reason,
        frame: data.frame, last_render_end_frame: data.last_render_end_frame });
    }
    function activate(generation) {
      const signal = deferred(); activated.set(generation, signal);
      node.port.postMessage({ type: 'activate', generation,
        trigger_samples: generation === 1 ? trigger_samples : null });
      return guard(signal.promise);
    }
    function snapshot() {
      const request_id = `snapshot-${++requestSequence}`;
      const signal = deferred(); snapshots.set(request_id, signal);
      node.port.postMessage({ type: 'snapshot', request_id });
      return guard(signal.promise);
    }
    function onWorklet(data) {
      event(data.type, data, 'worklet');
      if (data.quantum_frames) record.quantum_frames = data.quantum_frames;
      if (data.type === 'probe_ready') { record.probe_ready = data; probe.resolve(data); }
      if (data.generations) for (const [generation, state] of Object.entries(data.generations)) merge(Number(generation), state);
      if (data.type === 'snapshot') snapshots.get(data.request_id)?.resolve(data);
      if (data.type === 'activated') {
        record.generations[data.generation].activated = true;
        activated.get(data.generation)?.resolve(data);
      }
      if (data.type === 'activation_rejected') throw new Error(`activate rejected: ${data.reason}`);
      if (data.type === 'trigger') {
        if (cancelled || data.generation !== 1 || data.played !== trigger_samples)
          throw new Error('invalid or repeated trigger');
        cancelled = true;
        record.trigger = { ...data, notification_performance_ms: performance.now() };
        send({ type: 'cancel', generation: 1, played: data.played });
        if (policy === 'full') {
          node.port.postMessage({ type: 'flush', generation: 1 });
          event('flush_posted', { generation: 1 });
        }
      }
      if (data.type === 'flush_ack') {
        if (policy !== 'full' || data.generation !== 1) throw new Error('unexpected flush_ack');
        flushPlayed = data.played;
        record.flush_ack = { ...data, notification_performance_ms: performance.now() };
        playbackStopped(1, data, 'flush_ack');
      }
      if (data.type === 'queueempty') {
        merge(data.generation, data);
        if (data.done && serverDone.has(data.generation) &&
            (data.generation === 2 || policy === 'server_only'))
          playbackStopped(data.generation, data, 'generation_done_and_queueempty');
      }
      if (data.type === 'rejected') {
        if (data.stale_probe) {
          record.stale_rejection_count++;
          if (data.reason === 'generation_fence') record.stale_fence_rejection_count++;
          else record.validation_errors.push(`controlled stale probe rejected by ${data.reason}, expected generation_fence`);
        } else if (data.reason !== 'generation_fence' || policy !== 'full' || data.generation !== 1) {
          record.validation_errors.push(`unexpected PCM rejection: ${data.reason}`);
        }
      }
      if (data.type === 'enqueued' && data.stale_probe)
        record.validation_errors.push('controlled stale probe was accepted');
    }
    function onServer(message) {
      const generation = message.generation;
      if (message.type === 'audio' || message.type === 'stale_probe') {
        if (generation !== 1 && generation !== 2) throw new Error('bad PCM generation');
        const samples = decodePCM(message.pcm);
        const stale = message.type === 'stale_probe';
        const stats = record.generations[generation];
        stats[stale ? 'controlled_probe_samples' : 'received_samples'] += samples.length;
        stats[stale ? 'controlled_probe_frames' : 'received_frames']++;
        event(`${message.type}_received`, { generation, segment: message.segment, offset: message.offset,
          samples: samples.length, controlled: message.controlled === true }, 'server');
        if (stale && policy === 'server_only' && message.controlled === true) {
          record.ignored_controlled_probe++;
          event('ignored_controlled_probe', { generation, offset: message.offset, samples: samples.length });
          return;
        }
        // Full-policy stale probes deliberately use the identical worklet enqueue route.
        node.port.postMessage({ type: stale ? 'stale_probe' : 'enqueue', generation,
          segment: message.segment, offset: message.offset, samples,
          stale_probe: stale, probe_id: message.probe_id ?? null }, [samples.buffer]);
        return;
      }
      record.server_messages.push({ ...message, received_performance_ms: performance.now() });
      event(message.type, message, 'server');
      switch (message.type) {
        case 'ready':
          if (message.output_rate !== RATE) throw new Error(`server output_rate=${message.output_rate}`);
          record.server_ready = message; ready.resolve(message); break;
        case 'segment': record.segments.push(message); break;
        case 'generation_done':
          serverDone.add(generation);
          record.generations[generation].sent = message.sent;
          record.generations[generation].server_state = message.state;
          node.port.postMessage({ type: 'generation_done', generation }); break;
        case 'workers_joined': workersJoined.add(generation); record.generations[generation].workers_joined = message; break;
        case 'history': record.history.push(message); break;
        case 'next_ready':
          if (nextStarted || !stopped.has(1) || !serverDone.has(1) || !workersJoined.has(1))
            throw new Error('next_ready before generation 1 playback stop and worker join');
          nextStarted = true;
          activate(2).then(() => send({ type: 'start_next' })).catch(fail); break;
        case 'await_client_result':
          if (!stopped.has(2) || !serverDone.has(2)) throw new Error('early await_client_result');
          complete.resolve(message); break;
        case 'finished':
          if (!resultSent) throw new Error('finished before client_result');
          finishedSeen = true; record.server_finished = message; finished.resolve(message); break;
        case 'error': throw new Error(`server: ${message.error ?? JSON.stringify(message)}`);
      }
    }
    function summarize() {
      const old = record.generations[1], next = record.generations[2];
      record.last_old_render_end_frame = old.last_render_end_frame ?? null;
      record.trigger_to_last_old_render_ms = record.trigger && old.last_render_end_frame !== null
        ? (old.last_render_end_frame - record.trigger.frame) * 1000 / RATE : null;
      record.trigger_notification_to_flush_ack_notification_ms = record.flush_ack
        ? record.flush_ack.notification_performance_ms - record.trigger.notification_performance_ms : null;
      record.trigger_to_flush_ack_audio_ms = record.flush_ack
        ? (record.flush_ack.frame - record.trigger.frame) * 1000 / RATE : null;
      record.played_after_trigger_samples = record.trigger ? old.played - record.trigger.played : null;
      const check = (condition, reason) => { if (!condition) record.validation_errors.push(reason); };
      check(record.context_rate === RATE && record.probe_ready?.sample_rate === RATE, '24kHz AudioContext not verified');
      check(record.trigger?.played === trigger_samples, 'precise trigger missing');
      check(record.trigger_to_last_old_render_ms !== null && record.trigger_to_last_old_render_ms >= 0,
        'audio frame stop measurement missing or negative');
      for (const stats of [old, next]) {
        check(Number.isSafeInteger(stats.sent) && stats.sent === stats.received_samples, `generation ${stats.generation} server/client sent mismatch`);
        check(stats.accepted === stats.played + stats.queued + stats.discarded, `generation ${stats.generation} PCM conservation failed`);
        check(stats.queued === 0, `generation ${stats.generation} queue did not drain`);
      }
      check(next.played > 0 && next.played === next.sent, 'generation 2 was not fully rendered');
      if (policy === 'full') {
        check(Boolean(record.flush_ack), 'flush acknowledgement missing');
        check(record.stale_fence_rejection_count >= 1, 'controlled stale generation fence not observed');
        check(old.invalid === true && old.played === flushPlayed, 'old generation fence or frozen consumption missing');
      } else {
        check(old.played === old.sent, 'server_only old tail was not fully rendered');
        check(record.ignored_controlled_probe >= 1, 'controlled probe was not recorded as ignored');
      }
      record.valid = record.validation_errors.length === 0;
      record.outcome = record.valid ? 'complete' : 'invalid';
    }
    deadlineTimer = setTimeout(() => fail(new Error(`run timeout after ${timeout_ms}ms`)), Math.min(timeout_ms, 90000));
    try {
      if ($('#status')) $('#status').textContent = `${run_id}: warming AudioContext`;
      ctx = new AudioContext({ sampleRate: RATE });
      record.context_rate = ctx.sampleRate;
      record.audio_context_base_latency = ctx.baseLatency;
      record.audio_context_output_latency = ctx.outputLatency ?? null;
      if (ctx.sampleRate !== RATE) throw new Error(`AudioContext actual sampleRate=${ctx.sampleRate}, expected ${RATE}`);
      await guard(ctx.resume());
      silence = ctx.createConstantSource(); silence.offset.value = 0;
      silence.connect(ctx.destination); silence.start();
      await guard(new Promise(resolve => {
        const wait = () => cleaningUp || ctx.currentTime >= 0.12 ? resolve() : setTimeout(wait, 10);
        wait();
      }));
      event('context_warmup_complete', { sample_rate: ctx.sampleRate });
      await guard(ctx.audioWorklet.addModule(new URL('worklet.js', document.baseURI).href));
      node = new AudioWorkletNode(ctx, 'exp16-playback', {
        numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1],
        processorOptions: { trigger_samples, warmup_quanta: 8 },
      });
      node.onprocessorerror = () => fail(new Error('AudioWorklet processor error'));
      node.port.onmessage = ({ data }) => { try { onWorklet(data); } catch (error) { fail(error); } };
      node.connect(ctx.destination);
      await guard(probe.promise);
      const endpoint = new URL('/ws', location.href);
      endpoint.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      endpoint.searchParams.set('run_id', run_id);
      ws = new WebSocket(endpoint);
      ws.onmessage = ({ data }) => { try { onServer(JSON.parse(data)); } catch (error) { fail(error); } };
      ws.onerror = () => fail(new Error('WebSocket transport error'));
      ws.onclose = ({ code, reason }) => {
        event('ws_closed', { code, reason });
        if (!finishedSeen) fail(new Error(`WS closed before finished (${code}: ${reason})`));
      };
      await guard(ready.promise);
      await activate(1);
      send({ type: 'start', policy, trigger_samples });
      ackTimer = setInterval(() => {
        snapshot().then(data => {
          snapshots.delete(data.request_id);
          if (resultSent || finishedSeen) return;
          for (const [generation, state] of Object.entries(data.generations))
            if (record.generations[generation].activated) ack(Number(generation), state.played);
        }).catch(fail);
      }, 100);
      await guard(complete.promise);
      clearInterval(ackTimer);
      const finalSnapshot = await snapshot(); snapshots.delete(finalSnapshot.request_id);
      summarize();
      event('client_result_ready', { valid: record.valid });
      record.result_transport = 'ws';
      resultSent = true;
      send({ type: 'client_result', record });
      await guard(finished.promise);
    } catch (error) {
      record.error = String(error);
      record.outcome = 'error'; record.valid = false;
      event('client_error', { error: record.error });
      // Optional persistence fallback; this server may intentionally provide only WS.
      try {
        const response = await fetch(`/client-result?run_id=${encodeURIComponent(run_id)}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(record), signal: AbortSignal.timeout(2500),
        });
        record.fallback_post_status = response.status;
      } catch (persistError) { record.fallback_post_error = String(persistError); }
    } finally {
      cleaningUp = true;
      clearTimeout(deadlineTimer); clearInterval(ackTimer);
      if (ws) { ws.onclose = null; ws.close(); }
      if (node) { node.port.onmessage = null; node.disconnect(); node.port.close(); }
      if (silence) { silence.stop(); silence.disconnect(); }
      if (ctx && ctx.state !== 'closed') await ctx.close();
      record.ended_at = new Date().toISOString();
      record.elapsed_ms = Date.parse(record.ended_at) - Date.parse(record.started_at);
      event('client_finished');
      active = false;
      show(record);
    }
    return record;
  };
  if ($('#run')) $('#run').onclick = () => {
    window.runExp16({ policy: $('#policy').value, trigger_samples: Number($('#trigger').value) })
      .catch(error => { $('#status').textContent = String(error); });
  };
  window.exp16Ready = true;
})();
