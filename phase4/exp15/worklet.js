class MediaProbe extends AudioWorkletProcessor {
  constructor(options) {
    super();this.kind=options.processorOptions.kind;this.queue=[];this.position=0;
    this.buffered=0;this.consumed=0;this.expected=options.processorOptions.total;
    this.started=false;this.terminal=false;this.finished=false;this.underrun=0;
    this.first=null;this.toneRun=0;this.markerSeen=false;this.markerEnd=null;
    this.maxBuffer=0;this.lastReport=0;this.readySent=false;
    this.port.onmessage=({data})=>{
      if(data.type==='pcm') {this.queue.push(new Float32Array(data.samples));this.buffered+=data.samples.length;this.maxBuffer=Math.max(this.maxBuffer,this.buffered);}
      if(data.type==='terminal')this.terminal=true;
    };
  }
  emit(type,more={}) {this.port.postMessage({type,frame:currentFrame,consumed:this.consumed,underrun_samples:this.underrun,max_buffer_samples:this.maxBuffer,...more});}
  process(inputs,outputs) {
    if(!this.readySent){this.readySent=true;this.emit('probe_ready');}
    const output=outputs[0][0], n=output.length;
    if(this.kind==='ws') {
      if(!this.started && (this.buffered>=2880 || (this.terminal&&this.buffered>0)))this.started=true;
      if(this.started&&!this.finished)for(let i=0;i<n;i++){
        if(this.queue.length){output[i]=this.queue[0][this.position++];this.buffered--;this.consumed++;
          if(this.position===this.queue[0].length){this.queue.shift();this.position=0;}}
        else if(this.consumed<this.expected)this.underrun++;
      }
    } else {
      const input=inputs[0];
      if(input&&input.length)for(let i=0;i<n;i++){
        let value=0;for(let c=0;c<input.length;c++)value+=input[c][i]||0;
        output[i]=value/input.length;
      }
    }
    let energy=0,real=0,imag=0;
    for(let i=0;i<n;i++){
      const v=output[i];energy+=v*v;
      if(this.first===null&&Math.abs(v)>.01){this.first=currentFrame+i;this.emit('first_non_silent',{sample_frame:this.first});}
      const phase=2*Math.PI*2000*i/sampleRate;real+=v*Math.cos(phase);imag+=v*Math.sin(phase);
    }
    const tone=2*Math.hypot(real,imag)/n;
    if(tone>.075){this.toneRun+=n;if(this.toneRun>=sampleRate*.055)this.markerSeen=true;}
    else {if(this.markerSeen&&this.markerEnd===null){this.markerEnd=currentFrame;this.emit('end_probe_rendered',{sample_frame:this.markerEnd});}this.toneRun=0;}
    if(currentFrame-this.lastReport>=sampleRate*.1){this.emit('progress');this.lastReport=currentFrame;}
    if(!this.finished && ((this.kind==='ws'&&this.terminal&&this.consumed===this.expected)||
       (this.kind==='rtc'&&this.markerEnd!==null&&currentFrame-this.markerEnd>=sampleRate*.25))) {
      this.finished=true;this.emit('finished',{sample_frame:currentFrame+n,first_frame:this.first,end_probe_frame:this.markerEnd});
    }
    return true;
  }
}
registerProcessor('media-probe',MediaProbe);
