// Read-only WeChat draft inventory/readback using the installed skill's auth resolver.
// No tokens or credentials are persisted or printed.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {loadWechatExtendConfig, resolveAccount, loadCredentials} from '/home/researcher/.agents/skills/baoyu-post-to-wechat/scripts/wechat-extend-config.ts';

const [mode, planPath] = process.argv.slice(2);
if (!['list','verify'].includes(mode) || !planPath) throw new Error('usage: list|verify plan.json');
const plan=JSON.parse(fs.readFileSync(planPath,'utf8'));
const resolved=resolveAccount(loadWechatExtendConfig());
const creds=loadCredentials(resolved);
const tokenResponse=await fetch('https://api.weixin.qq.com/cgi-bin/token?'+new URLSearchParams({
  grant_type:'client_credential',appid:creds.appId,secret:creds.appSecret
}),{signal:AbortSignal.timeout(25000)});
const auth:any=await tokenResponse.json();
if(!tokenResponse.ok || !auth.access_token || auth.errcode) throw new Error(`token rejected: ${auth.errcode??tokenResponse.status}`);
async function api(endpoint:string, body:unknown){
  const response=await fetch('https://api.weixin.qq.com/cgi-bin/draft/'+endpoint+'?access_token='+encodeURIComponent(auth.access_token),{
    method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(25000)
  });
  const value:any=await response.json();
  if(!response.ok || value.errcode) throw new Error(`draft/${endpoint} rejected: ${value.errcode??response.status}`);
  return value;
}
const out=path.dirname(planPath);
if(mode==='list'){
  const matches:any[]=[];let offset=0,total=Infinity;
  while(offset<total){
    const data=await api('batchget',{offset,count:20,no_content:1});
    total=data.total_count;
    if(!Number.isInteger(total)) throw new Error('missing total_count');
    const items=data.item??[];
    if(!items.length && offset<total) throw new Error('incomplete pagination');
    for(const item of items){
      for(const a of item.content?.news_item??[]){
        if(plan.articles.some((p:any)=>a.title===p.title) || /^进化之路 P4·/.test(a.title??'')){
          matches.push({media_id:item.media_id,title:a.title,thumb_media_id:a.thumb_media_id,digest:a.digest});
        }
      }
    }
    offset+=items.length;
  }
  const result={checked_at:new Date().toISOString(),total,scanned:offset,matches,credential_source:creds.source};
  fs.writeFileSync(path.join(out,'draft-inventory-before.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
}else{
  const rows=[];
  for(const p of plan.articles){
    const receipt=JSON.parse(fs.readFileSync(path.join(p.stage,'upload-result.json'),'utf8'));
    if(!receipt.success || !receipt.media_id) throw new Error('missing upload receipt');
    const value=await api('get',{media_id:receipt.media_id});
    if(value.news_item?.length!==1) throw new Error('unexpected article count');
    const a=value.news_item[0];
    const html=a.content??'';
    const images=[...html.matchAll(/<img\b[^>]*\bsrc=["']([^"']+)/gi)].map((m:any)=>m[1]);
    const checks={title:a.title===p.title,digest:a.digest===p.summary,cover:!!a.thumb_media_id&&a.thumb_media_id===receipt.cover_media_id,
      comment_open:a.need_open_comment===1,comment_all:a.only_fans_can_comment===0,
      image_count:images.length===p.expected_images,
      images_hosted:images.length>0&&images.every((s:string)=>/^https?:\/\/(?:mmbiz\.qpic\.cn|mmbiz\.qlogo\.cn)\//.test(s)),
      phase_color:html.toLowerCase().includes('#e06c75')||html.includes('224, 108, 117'),
      no_placeholders:!/(?:MDTOHTMLIMGPH_|WECHATIMGPH_)/.test(html),
      no_local_image_src:!images.some((s:string)=>s.startsWith('/')||s.startsWith('img/')||s.startsWith('file:')),
      expected_headings:p.expected_headings.every((h:string)=>html.includes(h))};
    const result={checked_at:new Date().toISOString(),media_id:receipt.media_id,title:a.title,digest:a.digest,
      thumb_media_id:a.thumb_media_id,url:a.url,need_open_comment:a.need_open_comment,only_fans_can_comment:a.only_fans_can_comment,
      image_urls:images,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),checks,all_checks_pass:Object.values(checks).every(Boolean)};
    fs.writeFileSync(path.join(p.stage,'draft-readback.json'),JSON.stringify(result,null,2)+'\n');
    fs.writeFileSync(path.join(p.stage,'draft-readback.html'),html);
    rows.push(result);
  }
  const result={checked_at:new Date().toISOString(),articles:rows,all_checks_pass:rows.every(r=>r.all_checks_pass)};
  fs.writeFileSync(path.join(out,'batch-readback.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({all_checks_pass:result.all_checks_pass,articles:rows.map(r=>({title:r.title,media_id:r.media_id,checks:r.checks}))}));
  if(!result.all_checks_pass) process.exitCode=1;
}
