const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
  const output=path.resolve('phase4/results/exp15/sessions/browser-playback');fs.mkdirSync(output,{recursive:false});
  const browser=await chromium.launch({headless:true,channel:'chrome',ignoreDefaultArgs:['--mute-audio']});
  const page=await browser.newPage({viewport:{width:1100,height:850}});
  try{
    await page.goto('http://127.0.0.1:18145');
    await page.evaluate(async()=>{
      const {playSession}=await import('http://127.0.0.1:18146/session-client.js');
      const button=document.createElement('button');button.textContent='播放并排空会话';button.id='session-probe';document.body.prepend(button);
      button.onclick=async()=>{
        try{
          const controller=await playSession({sessionId:'browser-drain-a',owner:'a',generation:'browser-turn-1',initialBufferMs:600});
          const played=await controller.played,done=await controller.done;
          const snapshot=await (await fetch('http://127.0.0.1:18146/state')).json();
          const {events:unusedPlayed,...p}=played;const {events:unusedDone,...d}=done;
          window.sessionResult={played:p,done:d,events:controller.events,snapshot,headless:true,acoustic_loopback:false};
          const view=document.createElement('pre');view.textContent=JSON.stringify({played:p,terminal:done.terminal.worker},null,2);document.body.appendChild(view);
        }catch(e){window.sessionResult={error:String(e)};}
      };
    });
    await page.locator('#session-probe').click();
    await page.waitForFunction(()=>window.sessionResult,{timeout:15000});
    const result=await page.evaluate(()=>window.sessionResult);
    fs.writeFileSync(path.join(output,'record.json'),JSON.stringify(result,null,2)+'\n');
    await page.screenshot({path:path.join(output,'browser.png'),fullPage:true});
    if(result.error)throw new Error(result.error);
    const producer=result.events.find(e=>e.event==='producer_done_observed');
    const finished=result.events.find(e=>e.event==='worklet'&&e.observation.type==='finished');
    const report={browserVersion:browser.version(),producer_unrendered_samples:producer.unrendered_samples_at_observation,
      producer_to_finished_ms:finished.performance_ms-producer.performance_ms,
      rendered_samples:result.played.played_samples_cumulative,worker_status:result.snapshot.workers.a.status,
      ack_source:result.played.ack_source,acoustic_loopback:false};
    if(!(report.producer_unrendered_samples>0&&report.producer_to_finished_ms>0&&report.rendered_samples===149760&&report.worker_status==='drained'))throw new Error('browser drain invariant failed');
    fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
