const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async()=>{
  const args=process.argv.slice(2),value=(key,fallback)=>{const i=args.indexOf(key);return i<0?fallback:args[i+1];};
  const url=value('--url','http://127.0.0.1:18145');
  const output=path.resolve(value('--output','phase4/results/exp15/browser-new'));
  const mode=value('--mode','smoke'),repeat=Number(value('--repeat','3'));
  const headless=!args.includes('--headful');
  fs.mkdirSync(output,{recursive:false});
  const browser=await chromium.launch({headless,channel:'chrome',ignoreDefaultArgs:['--mute-audio'],args:['--autoplay-policy=no-user-gesture-required']});
  const page=await browser.newPage({viewport:{width:1200,height:860}});
  const log=[];page.on('pageerror',e=>log.push(String(e)));page.on('console',m=>{if(m.type()==='error')log.push(m.text());});
  try {await page.goto(url);await page.waitForFunction(()=>window.exp15Ready===true);}
  catch(error){await browser.close();throw error;}
  const config={url,mode,repeat,browserVersion:browser.version(),headless,startedAt:new Date().toISOString(),
    fixtureManifest:await page.evaluate(async()=>await (await fetch('/fixtures.json')).json()),records:[]};
  const schedule=[];
  if(mode==='smoke')for(const transport of ['ws','rtc'])schedule.push({transport,fixture:'short',scenario:'baseline'});
  else if(mode==='connectivity')for(const transport of ['ws','rtc'])schedule.push({transport,fixture:'short',scenario:'baseline'});
  else for(const scenario of ['baseline','source_pause'])for(let r=0;r<repeat;r++)for(const fixture of ['short','long'])
    for(const transport of r%2?['rtc','ws']:['ws','rtc'])schedule.push({transport,fixture,scenario,repeat:r});
  try{
    for(let i=0;i<schedule.length;i++){
      const item={...schedule[i],run_id:`${mode}-${i}-${Date.now()}`};
      const record=await page.evaluate(async item=>await window.runMedia(item),item);
      config.records.push({...record,repeat:item.repeat??null});
      fs.writeFileSync(path.join(output,'records.json'),JSON.stringify(config,null,2)+'\n');
      console.log(JSON.stringify({i:i+1,total:schedule.length,...item,outcome:record.outcome,connect_ms:record.connect_ms,first_render_ms:record.start_to_first_render_ms,underrun_ms:record.ws_underrun_ms,error:record.error}));
      if(mode==='smoke'&&record.outcome!=='complete')break;
    }
    await page.screenshot({path:path.join(output,'browser.png'),fullPage:true});
  }finally{
    config.endedAt=new Date().toISOString();config.pageErrors=log;
    fs.writeFileSync(path.join(output,'records.json'),JSON.stringify(config,null,2)+'\n');
    await browser.close();
  }
  if(config.records.some(r=>r.outcome!=='complete')&&mode!=='connectivity')process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
