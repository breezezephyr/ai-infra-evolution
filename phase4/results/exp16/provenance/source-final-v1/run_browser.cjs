'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function parseArgs(args) {
  const options = { url: 'http://127.0.0.1:18149', mode: 'smoke', repeat: 3,
    output: path.resolve(__dirname, '../results/exp16', `browser-${new Date().toISOString().replace(/[:.]/g, '-')}`),
    headless: true, channel: 'chrome' };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--headful') { options.headless = false; continue; }
    const compact = arg.match(/^--repeat(?:=)?(\d+)$/);
    if (compact) { options.repeat = Number(compact[1]); continue; }
    const [key, inline] = arg.split(/=(.*)/s);
    const name = { '--url': 'url', '--output': 'output', '--mode': 'mode', '--repeat': 'repeat', '--channel': 'channel' }[key];
    if (!name) throw new Error(`unknown argument: ${arg}`);
    const value = inline ?? args[++i];
    if (!value || value.startsWith('--')) throw new Error(`${key} requires a value`);
    options[name] = name === 'repeat' ? Number(value) : value;
  }
  if (!['smoke', 'formal'].includes(options.mode)) throw new Error('--mode must be smoke or formal');
  if (!Number.isInteger(options.repeat) || options.repeat < 1) throw new Error('--repeat must be a positive integer');
  const url = new URL(options.url);
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('--url must be HTTP or HTTPS');
  options.output = path.resolve(options.output);
  return options;
}

function scheduleFor({ mode, repeat }) {
  if (mode === 'smoke') return [{ policy: 'full', trigger_samples: 4800, repeat: 0 }];
  const schedule = [];
  for (const policy of ['server_only', 'full'])
    for (const trigger_samples of [4800, 24000, 96000])
      for (let index = 0; index < repeat; index++) schedule.push({ policy, trigger_samples, repeat: index });
  return schedule;
}

function loadPlaywright() {
  const candidates = ['playwright', process.env.PLAYWRIGHT_MODULE,
    path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')].filter(Boolean);
  for (const candidate of candidates) {
    try { return require(candidate); }
    catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
  }
  throw new Error('Playwright unavailable; install playwright or set PLAYWRIGHT_MODULE to its package path');
}

async function bounded(job, timeout, description) {
  let timer;
  try {
    return await Promise.race([Promise.resolve().then(job), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${description} after ${timeout}ms`)), timeout);
    })]);
  } finally { clearTimeout(timer); }
}

async function main(args = process.argv.slice(2)) {
  const options = parseArgs(args);
  // A new output directory prevents accidentally overwriting any previous evidence.
  fs.mkdirSync(path.dirname(options.output), { recursive: true });
  fs.mkdirSync(options.output, { recursive: false });
  const schedule = scheduleFor(options);
  const config = { ...options, started_at: new Date().toISOString(), timeout_per_run_ms: 90000,
    scope: 'real browser AudioContext/AudioWorklet rendering; headless runs do not establish acoustic listening quality',
    schedule, records: [], errors: [] };
  const save = () => fs.writeFileSync(path.join(options.output, 'records.json'), JSON.stringify(config, null, 2) + '\n');
  let browser;
  save();
  try {
    const { chromium } = loadPlaywright();
    browser = await chromium.launch({ headless: options.headless,
      ...(options.channel === 'chromium' ? {} : { channel: options.channel }),
      ignoreDefaultArgs: ['--mute-audio'], args: ['--autoplay-policy=no-user-gesture-required',
        '--disable-background-timer-throttling', '--disable-renderer-backgrounding'] });
    config.browser_version = browser.version(); save();
    for (let i = 0; i < schedule.length; i++) {
      const item = { ...schedule[i], run_id: `exp16-${options.mode}-${i}-${Date.now()}` };
      const errors = [];
      let page, record;
      try {
        record = await bounded(async () => {
          page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
          page.on('pageerror', error => errors.push(String(error)));
          page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
          await page.goto(options.url, { waitUntil: 'load', timeout: 20000 });
          await page.waitForFunction(() => window.exp16Ready === true, null, { timeout: 10000 });
          return await page.evaluate(config => window.runExp16(config), { ...item, timeout_ms: 85000 });
        }, 90000, `run ${item.run_id} timeout`);
      } catch (error) {
        let partial = null;
        if (page && !page.isClosed()) {
          try { partial = await bounded(() => page.evaluate(() => window.exp16LastRecord ?? null), 1000, 'partial record timeout'); }
          catch (_) { /* Keep the original failure even if the renderer is unavailable. */ }
        }
        record = { ...partial, ...item, valid: false, outcome: 'error', error: String(error) };
      } finally {
        record ??= { ...item, outcome: 'error', error: 'run ended without a record', valid: false };
        Object.assign(record, { repeat: item.repeat, page_errors: errors });
        config.records.push(record); save();
        if (page && !page.isClosed()) {
          const filename = `${String(i + 1).padStart(3, '0')}-${item.policy}-${item.trigger_samples}-r${item.repeat + 1}.png`;
          try {
            await page.screenshot({ path: path.join(options.output, filename), fullPage: true, timeout: 5000 });
            record.screenshot = filename;
            fs.copyFileSync(path.join(options.output, filename), path.join(options.output, 'browser.png'));
          } catch (error) { record.screenshot_error = String(error); }
          try { await page.close(); } catch (error) { record.page_close_error = String(error); }
        }
        save();
      }
      console.log(JSON.stringify({ run: i + 1, total: schedule.length, ...item,
        outcome: record.outcome, context_rate: record.context_rate, quantum_frames: record.quantum_frames,
        trigger_to_last_old_render_ms: record.trigger_to_last_old_render_ms,
        trigger_notification_to_flush_ack_notification_ms: record.trigger_notification_to_flush_ack_notification_ms,
        stale_rejection_count: record.stale_rejection_count, ignored_controlled_probe: record.ignored_controlled_probe,
        played: Object.fromEntries(Object.entries(record.generations ?? {}).map(([generation, state]) => [generation, state.played])),
        error: record.error, validation_errors: record.validation_errors }));
    }
  } catch (error) {
    config.errors.push(String(error));
    process.exitCode = 1;
  } finally {
    if (browser) {
      try { await browser.close(); } catch (error) { config.errors.push(`browser.close: ${error}`); }
    }
    config.ended_at = new Date().toISOString();
    config.completed_runs = config.records.filter(record => record.outcome === 'complete' && record.valid).length;
    config.failed_runs = config.records.length - config.completed_runs;
    save();
  }
  if (config.errors.length || config.failed_runs || config.records.length !== schedule.length) process.exitCode = 1;
  return config;
}

module.exports = { main, parseArgs, scheduleFor };
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
