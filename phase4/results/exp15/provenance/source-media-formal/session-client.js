/* Browser adapter for session_http.py; ACKs come only from AudioWorklet consumed.
 * Invoke playSession() from a user gesture. This module has NOT itself been
 * browser-validated by run_sessions.py; that runner uses synthetic ACKs.
 */
export async function playSession({
  base = 'http://127.0.0.1:18146', sessionId = crypto.randomUUID(),
  owner = 'a', generation = crypto.randomUUID(), initialBufferMs = 600,
  drainOnProducerDone = true, autoRelease = true, onEvent = () => {},
} = {}) {
  if (!Number.isFinite(initialBufferMs) || initialBufferMs < 600)
    throw new Error('initialBufferMs must be at least 600');
  const context = new AudioContext({sampleRate: 48000});
  // Start/resume synchronously before the first await to retain user activation.
  const resumed = context.resume();
  if (context.sampleRate !== 48000) {
    await context.close();
    throw new Error('This fixed PCM adapter requires a 48kHz AudioContext');
  }
  const events = [];
  const emit = (event, data = {}) => {
    const entry = {event, performance_ms: performance.now(), ...data};
    events.push(entry); onEvent(entry); return entry;
  };
  const request = async (path, body) => {
    const response = await fetch(base + path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    const result = await response.json();
    emit('http', {path, status: response.status, response: result});
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  };
  let session;
  try {
    await resumed;
    await context.audioWorklet.addModule(base + '/worklet.js');
    session = await request('/sessions', {session_id: sessionId, preferred_owner: owner});
  } catch (error) { await context.close(); throw error; }
  const url = new URL(base + '/session-ws');
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('session_id', sessionId);
  url.searchParams.set('owner', session.owner);
  const socket = new WebSocket(url); socket.binaryType = 'arraybuffer';
  let epoch, node, total, resumeFrom = 0, expectedOffset = 0, expectedSeq = 0;
  let consumed = 0, lastAck = -1, pending = [], buffered = 0, deliveredToWorklet = false;
  let producerDoneAt = null, drainPromise = Promise.resolve(), settled = false;
  let resolveReady, rejectReady, resolvePlayed, rejectPlayed, resolveDone, rejectDone;
  const ready = new Promise((yes, no) => {resolveReady = yes; rejectReady = no;});
  const played = new Promise((yes, no) => {resolvePlayed = yes; rejectPlayed = no;});
  const done = new Promise((yes, no) => {resolveDone = yes; rejectDone = no;});
  // Callers may only await done; keep optional played promise from warning.
  played.catch(() => {}); done.catch(() => {});
  const send = (type, fields = {}) => {
    const command = {type, epoch, ...fields};
    if (type === 'begin' || type === 'ack') command.generation = generation;
    emit('ws_send', {command}); socket.send(JSON.stringify(command));
  };
  const fail = error => {
    if (settled) return;
    settled = true; emit('error', {message: String(error)});
    rejectReady(error); rejectPlayed(error); rejectDone(error);
    socket.close(); if (node) node.disconnect(); void context.close();
  };
  const ack = () => {
    const absolute = resumeFrom + consumed;
    if (absolute > lastAck) {
      send('ack', {played_samples_cumulative: absolute}); lastAck = absolute;
    }
  };
  const flush = terminal => {
    if (!deliveredToWorklet && buffered < initialBufferMs * 48 && !terminal) return;
    if (!deliveredToWorklet) {
      deliveredToWorklet = true;
      emit('initial_buffer_released', {buffered_samples: buffered, initial_buffer_ms: initialBufferMs});
    }
    for (const samples of pending)
      node.port.postMessage({type: 'pcm', samples}, [samples.buffer]);
    pending = []; buffered = 0;
  };
  const controller = {
    sessionId, generation, context, socket, events, played, done,
    state: () => request('/sessions/' + encodeURIComponent(sessionId)),
    drain: body => request('/workers/' + session.owner + '/drain', body || {}),
    release: () => send('release'),
    close: async () => {socket.close(); if (node) node.disconnect(); await context.close();},
  };
  socket.onmessage = ({data}) => {
    try {
      if (typeof data !== 'string') {
        if (!node || data.byteLength < 12) throw new Error('audio before begun or short header');
        const view = new DataView(data), seq = view.getUint32(0), offset = view.getUint32(4);
        const count = view.getUint32(8);
        if (seq !== expectedSeq || offset !== expectedOffset || count < 1 || count > 960 || data.byteLength !== 12 + count * 2)
          throw new Error('noncontiguous PCM frame');
        const samples = new Float32Array(count);
        for (let i = 0; i < count; i++) samples[i] = view.getInt16(12 + i * 2, true) / 32768;
        expectedSeq++; expectedOffset += count; pending.push(samples); buffered += count;
        emit('audio_received', {seq, sample_offset: offset, sample_count: count});
        flush(false); return;
      }
      const message = JSON.parse(data); emit('ws_receive', {message});
      if (message.type === 'attached') {
        epoch = message.session.epoch; total = message.audio.total_samples;
        send('begin');
      } else if (message.type === 'begun') {
        resumeFrom = message.session.resume_from; expectedOffset = resumeFrom;
        node = new AudioWorkletNode(context, 'media-probe', {
          numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1],
          processorOptions: {kind: 'ws', total: total - resumeFrom},
        });
        node.port.onmessage = ({data: observation}) => {
          try {
            if (settled) return;
            consumed = observation.consumed;
            emit('worklet', {observation, played_samples_cumulative: resumeFrom + consumed});
            if (observation.type === 'progress' || observation.type === 'finished') ack();
            if (observation.type === 'finished') {
              const result = {sessionId, generation, epoch, events,
                ack_source: 'audio_worklet_consumed', acoustic_loopback: false,
                producer_done_before_finished: producerDoneAt !== null,
                played_samples_cumulative: resumeFrom + consumed};
              resolvePlayed(result);
              if (autoRelease) void drainPromise.then(() => send('release')).catch(fail);
            }
          } catch (error) {fail(error);}
        };
        node.connect(context.destination); resolveReady(controller);
      } else if (message.type === 'producer_done') {
        producerDoneAt = performance.now();
        emit('producer_done_observed', {played_samples_cumulative: resumeFrom + consumed,
          unrendered_samples_at_observation: total - resumeFrom - consumed,
          note: 'consumed is latest worklet report, not an acoustic measurement'});
        flush(true); node.port.postMessage({type: 'terminal'});
        if (drainOnProducerDone) drainPromise = controller.drain({});
        drainPromise.catch(fail);
      } else if (message.type === 'released' || message.type === 'forced') {
        settled = true;
        const result = {status: message.type, terminal: message, events,
          ack_source: 'audio_worklet_consumed', acoustic_loopback: false};
        if (message.type === 'forced') resolvePlayed(result);
        resolveDone(result); socket.close(); if (node) node.disconnect(); void context.close();
      } else if (message.type === 'error') throw new Error(message.error);
    } catch (error) {fail(error);}
  };
  socket.onerror = () => fail(new Error('WebSocket error; inspect server-events.jsonl'));
  socket.onclose = event => {
    emit('ws_closed', {code: event.code, reason: event.reason});
    if (!settled) fail(new Error('Disconnected before release; retained state can be resumed with same IDs'));
  };
  return ready;
}
