"""Phase 5.2 explanation card adapted from the approved Phase 5.1 template.

Deterministic HTML; no measured experiment results or generated artwork.
Writes only beside this script.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '进化之路P5·2｜广播分几段：流式输出与工具调用'

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
.failure strong{font-size:27px;line-height:1.5;font-weight:700}
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
.state{display:grid;grid-template-columns:186px minmax(0,1fr);gap:14px;padding:5px 0;border-bottom:1px solid #eee8dc;font-size:23px;line-height:1.5}
.state:last-child{border-bottom:0}
.state b{font-weight:700;color:#1c1a17}
.state span{color:#6f695f}
.step h3 .mono{font-size:25px}
.boundary>strong{font-size:32px;letter-spacing:-.025em}
'''

BODY = '''
<div class="eyebrow">进化之路 · <span class="mono">P5·2</span></div>
<h1>广播分几段</h1>
<div class="sub">流式输出与工具调用</div>

<section class="four">
  <div class="info blue"><h2>老做法</h2><p>每收到一块，就当一段完整输出。</p></div>
  <div class="info orange"><h2>哪里失效</h2><div class="failures">
    <div class="failure"><strong>三种边界不同</strong><p>Text / Token / SSE 字节，<br>分块边界不能混用。</p></div>
    <div class="failure"><strong>标记会跨块</strong><p>thinking / 工具标记，<br>未必在单块内闭合。</p></div>
    <div class="failure"><strong>finish() 关闭输入</strong><p>关闭输入并收尾，<br>不等于后端 Finish。</p></div>
    <div class="failure"><strong>close() 是放弃</strong><p>客户端关闭，<br>不伪造自然完成。</p></div>
  </div></div>
  <div class="info green"><h2>新方案</h2><div class="flow">
    <div class="step"><span class="num">01</span><div><h3>合成后端 Text 或 Tokens</h3><p>固定原文与 tokenizer，改变输入切分。</p></div></div>
    <div class="step"><span class="num">02</span><div><h3>↓ 真实 recipe <span class="mono">StreamProcessor</span></h3><p>使用真实库，解析可能跨块的标记。</p></div></div>
    <div class="step"><span class="num">03</span><div><h3>↓ 协议事件</h3><p>先保存 event / data 快照，再分出 A / B 两支。</p></div></div>
    <div class="step"><span class="num">04</span><div><h3>分支 A：原生 <span class="mono">accumulate</span> 完整响应</h3><p>输入：原生协议事件对象。</p></div></div>
    <div class="step"><span class="num">05</span><div><h3>分支 B：本地 SSE 包装 → 字节拆分 → 读回</h3><p>输入：同一事件的 event / data 快照。</p></div></div>
  </div></div>
  <div class="info white"><h2>怎么验</h2><div>
    <div class="checks">
      <div class="check"><strong>固定原文与 tokenizer</strong><p>多切分，比较选定语义。</p></div>
      <div class="check"><strong>逐条记录终态</strong><p>完成信号与停止原因分清。</p></div>
      <div class="check"><strong>原始 usage / 来源分列</strong><p>保留原始值，标明来源。</p></div>
      <div class="check"><strong>工具只记录</strong><p>记录工具信息，不执行工具。</p></div>
    </div>
    <div class="states"><h3>结束状态，逐条区分依据</h3>
      <div class="state"><b>后端 Finish</b><span>后端给出完成信号。</span></div>
      <div class="state"><b>解析器停止</b><span>解析器决定停止。</span></div>
      <div class="state"><b>未证实 EOF</b><span>流已到头，完成尚未证实。</span></div>
      <div class="state"><b>客户端 close</b><span>客户端放弃，不是自然完成。</span></div>
      <div class="state"><b>错误</b><span>保留错误与结束上下文。</span></div>
    </div>
  </div></div>
</section>

<section class="boundary">
  <div class="takeaway">带走一条</div>
  <strong>分块可以变，完成依据不能含糊。</strong>
  <div class="limits">
    <p><b>实验范围：</b>CPU 真实库 ＋ 合成后端；本地 SSE 包装与读回。</p>
    <p><b>结论边界：</b>无模型推理、真实 HTTP 网络或工具执行。</p>
  </div>
</section>
<div class="footer">P5·2 · 流式输出与工具调用 · recipe 真实库 / CPU<br>解释卡 · 合成后端 / 本地 SSE 字节读回</div>
'''

def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)


if __name__ == '__main__':
    build()
