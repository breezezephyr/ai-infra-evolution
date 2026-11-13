const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/home/researcher/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const root = __dirname;
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  const page = await browser.newPage({viewport: {width: 390, height: 1000}, deviceScaleFactor: 2});
  await page.goto('file://' + root + '/正文.html');
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(i => i.complete ? Promise.resolve() : new Promise(resolve => {i.onload=resolve;i.onerror=resolve;})));
  });
  const report = await page.evaluate(() => ({
    viewport: innerWidth,
    pageWidth: document.documentElement.scrollWidth,
    pageHeight: document.documentElement.scrollHeight,
    images: [...document.images].map(i => ({src:i.getAttribute('src'),width:i.naturalWidth,height:i.naturalHeight,displayWidth:i.getBoundingClientRect().width})),
    tables: [...document.querySelectorAll('table')].map(t => ({columns:t.rows[0].cells.length,renderWidth:t.getBoundingClientRect().width,parentWidth:t.parentElement.clientWidth,parentOverflow:getComputedStyle(t.parentElement).overflowX})),
    headings: [...document.querySelectorAll('h2')].map(h=>h.textContent.trim()),
    unresolved: document.body.innerText.includes('MDTOHTMLIMGPH_'),
    literalBold: document.body.innerText.includes('**')
  }));
  await page.screenshot({path:path.join(root,'排版预览-首屏.png')});
  await page.getByRole('heading', {name:'五、120条请求，保留每一道门的分母', exact:true}).evaluate(el => el.scrollIntoView());
  await page.screenshot({path:path.join(root,'排版预览-浏览器.png')});
  fs.writeFileSync(path.join(root,'排版检查.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
  await browser.close();
})().catch(e => {console.error(e);process.exitCode=1;});
