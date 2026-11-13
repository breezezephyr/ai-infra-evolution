"""Phase 5.7 explanation card copied from the approved Phase 5.2 template.

Deterministic HTML; user-supplied experiment boundaries, no result counts.
Writes only beside this script.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '进化之路P5·7｜把站台接起来：一个能对账的网关'

CSS = '''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:2080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:58px 76px 48px;display:flex;flex-direction:column}
body>*{flex-shrink:0}
.mono{font-family:Menlo,"SF Mono",monospace}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:24px;line-height:1.3;letter-spacing:.035em}
.eyebrow::before{content:"";width:34px;height:5px;background:#F2D479;border-radius:3px}
h1{font-size:58px;line-height:1.4;font-weight:800;letter-spacing:-.015em;margin-top:20px}
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
.account+.account{margin-top:14px;border-top:2px solid #d0e1cf;padding-top:14px}
.account-head{display:flex;align-items:center;gap:16px;margin-bottom:6px}
.account h3{font-size:28px;line-height:1.5;font-weight:800}
.account .tag{font-size:22px;line-height:1.5;color:#4f7a52}
.account p{font-size:26px;line-height:1.55}
.formula{margin-top:16px;border-top:2px solid #d0e1cf;padding-top:14px}
.formula-label{font-size:22px;line-height:1.5;color:#4f7a52;font-weight:700;margin-bottom:6px}
.formula-main{font-size:26px;line-height:1.5;font-weight:800;letter-spacing:-.025em;white-space:nowrap}
.formula-note{font-size:23px;line-height:1.5;color:#6f695f;margin-top:6px}
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

.flow{display:grid;gap:10px}
.step{display:grid;grid-template-columns:34px minmax(0,1fr);gap:14px;position:relative;padding-bottom:10px;border-bottom:2px solid #d0e1cf}
.step:last-child{padding-bottom:0;border-bottom:0}
.step:nth-child(2),.step:nth-child(3){border-bottom-style:dashed}
.step .num{font:700 18px/30px Menlo,monospace;text-align:center;width:32px;height:32px;border:1.5px solid #a9c4a6;border-radius:50%;color:#4f7a52;margin-top:3px}
.step h3{font-size:27px;line-height:1.4;font-weight:800}
.step p{font-size:23px;line-height:1.45;color:#6f695f;margin-top:2px}
.step.pending{border-top:2px dashed #b7c7b2;padding-top:12px}
.step.pending .num{border-style:dashed;color:#8a8378}
.pending-head{display:flex;align-items:center;gap:16px}
.pending-head .tag{font-size:21px;line-height:1.5;color:#6f695f;font-weight:500}
.input-count{font-size:23px;line-height:1.5;color:#6f695f;margin-top:14px;padding-top:12px;border-top:2px solid #eee8dc}
.input-count b{font-weight:800;color:#1c1a17}
.boundary .limits{gap:8px}

.states{margin-top:18px;padding-top:14px;border-top:2px solid #eee8dc}
.states h3{font-size:24px;line-height:1.5;font-weight:800;margin-bottom:8px}
.state{display:grid;grid-template-columns:160px minmax(0,1fr);gap:14px;padding:5px 0;border-bottom:1px solid #eee8dc;font-size:23px;line-height:1.5}
.state:last-child{border-bottom:0}
.state b{font-weight:700;color:#1c1a17}
.state span{color:#6f695f}
.step h3 .mono{font-size:25px}
.boundary>strong{font-size:30px;letter-spacing:-.025em}
'''

BODY = '''

<div class="eyebrow">进化之路 · <span class="mono">P5·7</span></div>
<h1>把站台接起来</h1><div class="sub">一个能对账的网关</div>
<section class="four">
<div class="info blue"><h2>老做法</h2><p>组件分别能用，最后再给成功请求补一笔账。</p></div>
<div class="info orange"><h2>哪里失效</h2><div class="failures">
<div class="failure"><strong>先查缓存，后认身份</strong><p>旧回答可能跨越租户、<br>模板或策略边界。</p></div>
<div class="failure"><strong>先交付，后做审核</strong><p>发现问题时，已发出的<br>正文无法自动撤回。</p></div>
<div class="failure"><strong>只给交付记成本</strong><p>被拦截、被截断的生成，<br>真实用量也会发生。</p></div>
<div class="failure"><strong>混用三个分母</strong><p>请求 / attempt / token，<br>不是同一件事。</p></div>
</div></div>
<div class="info green"><h2>新方案</h2><div class="flow">
<div class="step"><span class="num">01</span><div><h3>先检查身份、能力和预算</h3><p>租户从实验凭据映射；不支持的输入明确拒绝。</p></div></div>
<div class="step"><span class="num">02</span><div><h3>已审核精确缓存先分流</h3><p>命中绕过生成队列；保留原用量来源，不重复生成记账。</p></div></div>
<div class="step"><span class="num">03</span><div><h3>未命中再准入、路由和生成</h3><p>1个活跃＋1个等待名额；每次attempt有独立凭据。</p></div></div>
<div class="step"><span class="num">04</span><div><h3>整段门控后交付，终态都留账</h3><p>v1先收完后端流；拒绝交付仍保留已发生的usage。</p></div></div>
</div></div>
<div class="info white"><h2>怎么验</h2><div>
<div class="checks">
<div class="check"><strong>42条请求都有终态</strong><p>包括缓存、拒绝、审核和截断。</p></div>
<div class="check"><strong>12次真实生成attempt</strong><p>入口、输出流、usage逐项核对。</p></div>
<div class="check"><strong>7次缓存命中</strong><p>当前生成0，原生成来源单列。</p></div>
<div class="check"><strong>2次审核拦截</strong><p>正文未交付，54个token仍留账。</p></div>
</div>
<div class="states"><h3>三份记录，核对同一条链路</h3>
<div class="state"><b>客户端</b><span>真正收到的状态、正文与终止帧。</span></div>
<div class="state"><b>网关</b><span>关口顺序、身份、缓存与attempt。</span></div>
<div class="state"><b>后端</b><span>实际入口、输出流与原始usage。</span></div>
</div></div></div></section>
<section class="boundary"><div class="takeaway">带走一条</div><strong>交付、生成和用量，要能彼此对上。</strong>
<div class="limits"><p><b>本期实验：</b>单个Qwen小GPU，两个合成租户。</p>
<p><b>门控范围：</b>LAB_BLOCK规则；没有通用安全或质量保证。</p>
<p><b>结论边界：</b>响应缓存，非KV；没有容量、HA或货币账单。</p></div></section>
<div class="footer">P5·7 · 一个能对账的网关<br>解释卡 · 顺序 / 凭据 / 交付与生成分账</div>
'''

def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)

if __name__ == '__main__':
    build()
