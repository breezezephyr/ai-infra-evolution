"""P5.9 explanation card, reusing the approved P5.8 series template.

42 requests are a plan, not an executed result. Local, offline assets only.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '进化之路P5·9｜交班时拿什么说话：体验、资源与贡献'

CSS = '''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:2080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:58px 76px 48px;display:flex;flex-direction:column}
body>*{flex-shrink:0}
.mono{font-family:Menlo,"SF Mono",monospace}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:24px;line-height:1.3;letter-spacing:.035em}
.eyebrow::before{content:"";width:34px;height:5px;background:#F2D479;border-radius:3px}
h1{font-size:54px;line-height:1.4;font-weight:800;letter-spacing:-.015em;margin-top:20px}
.sub{font-size:27px;line-height:1.5;color:#6f695f;margin-top:10px}
.four{display:grid;gap:16px;margin-top:26px}
.info{display:grid;grid-template-columns:128px minmax(0,1fr);gap:20px;border:2px solid;border-radius:20px;padding:20px 26px;align-items:start}
.info h2{font-size:27px;line-height:1.6;font-weight:800;white-space:nowrap}
.info p{font-size:27px;line-height:1.5;letter-spacing:-.015em}
.blue{background:#edf4fa;border-color:#cfdeeb}.blue h2{color:#4b7190}
.orange{background:#fbf1e6;border-color:#f0dcc4}.orange h2{color:#b36c36}
.green{background:#edf5ed;border-color:#d0e1cf}.green h2{color:#4f7a52}
.white{background:#fff;border-color:#e6e0d4}.white h2{color:#6f695f}
.failures{display:grid;grid-template-columns:1fr 1fr;gap:16px 20px}
.failure strong{font-size:25px;line-height:1.5;font-weight:700}
.failure p{font-size:23px;line-height:1.5;color:#6f695f;margin-top:4px}
.checks{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px 20px}
.check{padding-bottom:10px;border-bottom:2px solid #eee8dc}
.check strong{font-size:26px;line-height:1.5;font-weight:700}
.check p{font-size:23px;line-height:1.5;color:#6f695f;margin-top:4px}
.check.wide{grid-column:1/-1;display:flex;align-items:baseline;gap:18px}
.check.wide p{margin-top:0}
.boundary{margin-top:24px;border-top:3px solid #F2D479;padding-top:20px}
.takeaway{font-size:24px;line-height:1.5;color:#88702f;font-weight:700;margin-bottom:8px}
.boundary>strong{display:block;font-size:32px;line-height:1.5;font-weight:800;white-space:nowrap}
.limits{margin-top:16px;display:grid;gap:8px}
.limits p{font-size:23px;line-height:1.5;color:#6f695f}
.limits b{font-weight:700;color:#6f695f}
.footer{font-size:22px;line-height:1.5;color:#9a9386;margin-top:auto;padding-top:22px}

.flow{display:grid;gap:8px}
.step{display:grid;grid-template-columns:34px minmax(0,1fr);gap:14px;position:relative;padding-bottom:8px;border-bottom:2px solid #d0e1cf}
.step:last-child{padding-bottom:0;border-bottom:0}
.step:nth-child(2),.step:nth-child(3){border-bottom-style:dashed}
.step .num{font:700 18px/30px Menlo,monospace;text-align:center;width:32px;height:32px;border:1.5px solid #a9c4a6;border-radius:50%;color:#4f7a52;margin-top:3px}
.step h3{font-size:27px;line-height:1.4;font-weight:800}
.step p{font-size:23px;line-height:1.45;color:#6f695f;margin-top:2px}
.step p .mono{font-size:22px}
.step p b{color:#1c1a17;font-weight:700}
.commit{color:#4f7a52}
.checks-note{font-size:22px;line-height:1.5;color:#6f695f;margin-bottom:12px}
.boundary>strong{font-size:30px;letter-spacing:-.025em}

.checks-note{font-size:23px;color:#6f695f}
.checks-note b{color:#1c1a17}
.plan-note{margin-top:12px;font-size:22px;line-height:1.5;color:#88702f}
.boundary>strong{font-size:30px;white-space:nowrap}
'''

BODY = '''
<div class="eyebrow">进化之路 · <span class="mono">P5·9</span></div>
<h1>交班时拿什么说话</h1><div class="sub">体验、资源与贡献</div>
<section class="four">
<div class="info blue"><h2>老做法</h2><p>把不同实验的成功率拼成总成绩。</p></div>
<div class="info orange"><h2>哪里失效</h2><div class="failures">
<div class="failure"><strong>HTTP 200 ≠ 完整回答</strong><p>状态码通过，<br>不代表内容完整、质量合格。</p></div>
<div class="failure"><strong>缓存命中 ≠ 新生成</strong><p>应用缓存复用已有答案，<br>不能冒充模型本轮生成。</p></div>
<div class="failure"><strong>取消有未知成本</strong><p>失败、取消仍保留分母；<br>缺失usage不能填0。</p></div>
<div class="failure"><strong>进程占用 ≠ kernel秒</strong><p>进程存活或显存占用，<br>都不是GPU kernel执行秒数。</p></div>
</div></div>
<div class="info green"><h2>新方案</h2><div class="flow">
<div class="step"><span class="num">01</span><div><h3>同request输入</h3><p>同一输入贯穿各层，保留租户与request ID。</p></div></div>
<div class="step"><span class="num">02</span><div><h3>协议</h3><p>检查完整流与终态；<b>有完整流不等于达标。</b></p></div></div>
<div class="step"><span class="num">03</span><div><h3>质量oracle</h3><p><b>答案精确匹配</b>，且<span class="mono">finish_reason=stop</span>。</p></div></div>
<div class="step"><span class="num">04</span><div><h3>客户端同钟SLO</h3><p>首内容与结束，均用客户端同一单调时钟。</p></div></div>
<div class="step"><span class="num">05</span><div><h3>缓存策略</h3><p>直通 / 集成冷 / 集成暖分层；应用缓存命中单列。</p></div></div>
<div class="step"><span class="num">06</span><div><h3>attempt账本与收拢</h3><p>每次尝试都留账；取消后<span class="mono">cancel/join</span>确认退出。</p></div></div>
</div></div>
<div class="info white"><h2>怎么验</h2><div>
<p class="checks-note"><b>42请求 / 37回答目标</b> · 两租户 × 3轮 · 各层分别汇报</p>
<div class="checks">
<div class="check"><strong>客户端实验门槛</strong><p>首内容 ≤1000ms<br>结束 ≤3000ms<br>协议、质量与时间同时过关。</p></div>
<div class="check"><strong>分母保留，未知披露</strong><p>失败、取消留在分母；<br>known usage与unknown分列。</p></div>
<div class="check"><strong>模型服务区间求并集</strong><p>重叠区间只计一次，<br>不按请求相加。</p></div>
<div class="check"><strong>贡献：可复现本地候选</strong><p>输入、脚本、证据可复跑；<br>非已合并PR。</p></div>
</div><div class="plan-note">formal-v2已实跑：21条回答目标联合通过。</div>
</div></div></section>
<section class="boundary"><div class="takeaway">带走一条</div><strong>交班，交的是一条能追到底的证据链。</strong>
<div class="limits"><p><b>范围：</b>单GPU / 文本 / 受控故障 / 应用缓存冷暖。</p>
<p><b>体验：</b>1000ms / 3000ms为实验门槛，不称生产SLO或容量。</p>
<p><b>资源：</b>服务区间是观测口径，不称GPU kernel秒或货币账单。</p></div></section>
<div class="footer">P5·9 · 体验、资源与贡献<br>收官解释卡 · 同request证据链 / 分母保留 / 未知披露</div>
'''

def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)


if __name__ == '__main__':
    build()
