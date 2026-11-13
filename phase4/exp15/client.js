const status=document.querySelector('#status');
let active=false;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function waitFor(test,timeout=12000){return new Promise((resolve,reject)=>{const start=performance.now();const t=setInterval(()=>{if(test()){clearInterval(t);resolve();}else if(performance.now()-start>timeout){clearInterval(t);reject(new Error('condition timeout'));}},20);});}
async function rtcStats(pc){const entries=[];for(const s of (await pc.getStats()).values())entries.push({...s});return entries;}

window.runMedia=async function({transport='ws',fixture='short',scenario='baseline',run_id=`${transport}-${Date.now()}`}={}) {
  if(active)throw new Error('one active run only');active=true;
  const record={run_id,transport,fixture_id:fixture,scenario,browser:navigator.userAgent,events:[],error:null,
    scope:'fixed audio replay with synthetic boundary probes; no inference; no acoustic loopback'};
  const ctx=new AudioContext({sampleRate:48000});await ctx.resume();
  // 让渲染时钟先运行；空图的 currentTime=0 会漏掉首次设备/图启动等待。
  const silence=ctx.createConstantSource();silence.offset.value=0;silence.connect(ctx.destination);silence.start();
  await waitFor(()=>ctx.currentTime>.1,4000);
  const event=(name,more={})=>record.events.push({event:name,performance_ms:performance.now(),context_time:ctx.currentTime,...more});
  let ws,pc,dc,node,source,element,received=0,nextSeq=0,ready,finished,arrivals=[];
  let complete,producerComplete;finished=new Promise(resolve=>{complete=resolve;});
  const producerFinished=new Promise(resolve=>{producerComplete=resolve;});
  const startedPerf=performance.now();record.connect_start_context=ctx.currentTime;
  function start(){record.ready_ms=performance.now();record.media_start_performance_ms=record.ready_ms;record.media_start_context=ctx.currentTime;event('start_sent');
    (transport==='ws'?ws:dc).send(JSON.stringify({type:'start'}));}
  async function setup(meta){
    record.fixture=meta;record.context_rate=ctx.sampleRate;
    if(ctx.sampleRate!==48000)throw new Error('requires 48k AudioContext');
    await ctx.audioWorklet.addModule('/worklet.js');
    node=new AudioWorkletNode(ctx,'media-probe',{numberOfInputs:transport==='rtc'?1:0,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{kind:transport,total:meta.samples}});
    node.connect(ctx.destination);
    let signalReady;const processing=new Promise(resolve=>{signalReady=resolve;});
    node.port.onmessage=({data})=>{
      if(data.type==='probe_ready')signalReady();
      if(data.type!=='progress')event(data.type,data);
      if(data.type==='first_non_silent'){record.first_non_silent_context=data.sample_frame/ctx.sampleRate;record.first_render_notification_performance_ms=performance.now();}
      if(transport==='ws'&&ws.readyState===WebSocket.OPEN&&(data.type==='progress'||data.type==='finished'))ws.send(JSON.stringify({type:'ack',samples:data.consumed}));
      if(data.type==='finished'){record.playback=data;complete();}
    };
    await Promise.race([processing,delay(4000).then(()=>{throw new Error('worklet did not start');})]);
    await delay(80);
  }
  try {
    if(transport==='ws') {
      ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);ws.binaryType='arraybuffer';
      ready=new Promise((resolve,reject)=>{
        ws.onopen=()=>ws.send(JSON.stringify({type:'start_request',run_id,fixture,scenario}));
        ws.onerror=()=>reject(new Error('WS failed'));
        ws.onmessage=async({data})=>{try{
          if(typeof data==='string'){
            const control=JSON.parse(data);
            if(control.type==='ready'){await setup(control.fixture);resolve();}
            if(control.type==='producer_done'){record.producer_done_received_ms=performance.now();node.port.postMessage({type:'terminal'});event('producer_done_received');}
          } else {
            const view=new DataView(data);if(view.getUint32(0)!==0x50343135)throw new Error('bad magic');
            const seq=view.getUint32(4),offset=view.getUint32(8),n=view.getUint32(12);
            if(seq!==nextSeq++||offset!==received||data.byteLength!==16+n*2)throw new Error('sequence/offset mismatch');
            received+=n;arrivals.push(performance.now());const values=new Float32Array(n);
            for(let i=0;i<n;i++)values[i]=view.getInt16(16+i*2,true)/32768;
            node.port.postMessage({type:'pcm',samples:values},[values.buffer]);
          }
        }catch(error){reject(error);record.error=String(error);complete();}};
      });
      await Promise.race([ready,delay(12000).then(()=>{throw new Error('WS ready timeout');})]);start();
    } else {
      pc=new RTCPeerConnection({iceServers:[]});record.rtc_events=[];
      for(const name of ['iceconnectionstatechange','connectionstatechange','icegatheringstatechange'])pc.addEventListener(name,()=>{record.rtc_events.push({event:name,at_ms:performance.now(),ice:pc.iceConnectionState,connection:pc.connectionState,gathering:pc.iceGatheringState});});
      const incoming=new Promise(resolve=>{pc.ontrack=({track,streams})=>resolve(new MediaStream([track]));});
      pc.addTransceiver('audio',{direction:'recvonly'});dc=pc.createDataChannel('control',{ordered:true});
      ready=new Promise((resolve,reject)=>{dc.onmessage=async({data})=>{try{const control=JSON.parse(data);if(control.type==='ready'){await setup(control.fixture);resolve();}if(control.type==='producer_done'){record.producer_done_received_ms=performance.now();event('producer_done_received');producerComplete();}}catch(e){reject(e);}};});
      await pc.setLocalDescription(await pc.createOffer());
      await waitFor(()=>pc.iceGatheringState==='complete',8000);
      record.offer_sdp=pc.localDescription.sdp;
      const response=await fetch('/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id,fixture,scenario,sdp:pc.localDescription.sdp,type:pc.localDescription.type})});
      if(!response.ok)throw new Error('offer HTTP '+response.status);
      const answer=await response.json();record.answer_sdp=answer.sdp;
      await pc.setRemoteDescription(answer);
      await Promise.race([ready,delay(15000).then(()=>{throw new Error('RTC media/control connection timeout');})]);
      // 元素激活远端播放；观察节点直接读 MediaStream。
      // Chromium 的 srcObject 媒体元素并不向 MediaElementSource 提供 PCM。
      const stream=await incoming;
      source=ctx.createMediaStreamSource(stream);source.connect(node);
      element=new Audio();element.autoplay=true;element.srcObject=stream;
      element.volume=0.000001;record.auxiliary_element_volume=element.volume;
      element.addEventListener('playing',()=>event('media_element_playing'));
      await Promise.race([element.play(),delay(3000).then(()=>{throw new Error('remote audio play timeout');})]);
      record.rtc_stats_start=await rtcStats(pc);start();
    }
    record.connect_ms=record.ready_ms-startedPerf;
    await Promise.race([finished,delay(record.fixture.seconds*1000+10000).then(()=>{throw new Error('playback timeout');})]);
    if(record.error)throw new Error(record.error);
    if(transport==='rtc')await Promise.race([producerFinished,delay(3000).then(()=>{throw new Error('media completed before source terminal; terminal timeout');})]);
    record.start_to_first_render_ms=record.first_render_notification_performance_ms-record.media_start_performance_ms;
    record.audio_clock_start_to_first_render_ms=1000*(record.first_non_silent_context-record.media_start_context);
    record.render_metric='main thread receipt of first non-silent AudioWorklet notification; includes message dispatch';
    record.connect_to_first_render_ms=1000*(record.first_non_silent_context-record.connect_start_context);
    if(transport==='ws'){
      record.received_samples=received;record.arrival_performance_ms=arrivals;
      if(received!==record.fixture.samples||record.playback.consumed!==received)throw new Error('PCM incomplete');
      record.ws_underrun_ms=record.playback.underrun_samples/48;
    } else {
      record.rtc_stats_end=await rtcStats(pc);
      record.ws_underrun_ms=null;
      record.rtc_completion='end probe rendered plus 250ms guard AND source producer_done received; not bit-exact source sample ACK';
      if(record.playback.end_probe_frame===null)throw new Error('end probe missing');
    }
    record.outcome='complete';
  } catch(error){record.error=String(error);record.outcome='error';if(pc)record.rtc_stats_end=await rtcStats(pc);}
  finally{
    event('client_finished');
    const response=await fetch('/results',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(record)});
    record.saved=response.ok;
    if(ws)ws.close();if(pc)pc.close();if(element){element.pause();element.srcObject=null;}if(source)source.disconnect();if(node)node.disconnect();silence.stop();await ctx.close();active=false;
  }
  const inbound=record.rtc_stats_end?.find(s=>s.type==='inbound-rtp'&&s.kind==='audio');
  const row=document.querySelector('#results').insertRow();
  for(const value of [`${transport} / ${fixture} / ${scenario}`,record.connect_ms?.toFixed(1)??'—',record.start_to_first_render_ms?.toFixed(1)??'—',record.ws_underrun_ms?.toFixed(1)??'—',inbound?.concealedSamples??'—',record.outcome])row.insertCell().textContent=value;
  document.querySelector('#record').textContent=JSON.stringify(record,null,2);status.textContent=`${run_id}: ${record.outcome}`;
  return record;
};
for(const kind of ['ws','rtc'])document.querySelector('#'+kind).onclick=()=>{window.runMedia({transport:kind,fixture:document.querySelector('#fixture').value,scenario:document.querySelector('#scenario').value}).catch(e=>{status.textContent=String(e);});};
window.exp15Ready=true;
