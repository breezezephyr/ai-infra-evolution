"""Phase 5.3 explanation card copied from the approved Phase 5.2 template.

Deterministic HTML; user-supplied experiment boundaries, no result counts.
Writes only beside this script.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '进化之路P5·3｜按格式报站：结构化输出谁来保证'

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
.boundary>strong{font-size:32px;letter-spacing:-.025em}
'''

BODY = '''
<div class="eyebrow">进化之路 · <span class="mono">P5·3</span></div>
<h1>按格式报站</h1>
<div class="sub">结构化输出谁来保证</div>

<section class="four">
  <div class="info blue"><h2>老做法</h2><p>声明 JSON / schema，就认为输出可靠。</p></div>
  <div class="info orange"><h2>哪里失效</h2><div class="failures">
    <div class="failure"><strong>请求接受 ≠ 执行约束</strong><p>参数被接受，<br>不等于采样时执行约束。</p></div>
    <div class="failure"><strong>JSON 可解析 ≠ schema 合格</strong><p>语法有效，<br>仍要逐项校验 schema。</p></div>
    <div class="failure"><strong>schema 合格 ≠ 业务答案正确</strong><p>字段与类型合规，<br>业务答案仍可能出错。</p></div>
    <div class="failure"><strong>工具约束 ≠ JSON 约束</strong><p>工具约束不能直接<br>当 JSON 约束透传。</p></div>
  </div></div>
  <div class="info green"><h2>新方案</h2><div class="flow">
    <div class="step"><span class="num">01</span><div><h3>声明</h3><p>JSON、schema、工具约束：先说明请求意图。</p></div></div>
    <div class="step"><span class="num">02</span><div><h3>CPU 线：真实 recipe 转换</h3><p>独立验证 recipe 转换与 parser，不接 GPU。</p></div></div>
    <div class="step"><span class="num">03</span><div><h3>两线核对：显式语义映射 / 拒绝</h3><p>核对语义对应字段，不串接两线产物。</p></div></div>
    <div class="step"><span class="num">04</span><div><h3>GPU 线：后端独立采样生成</h3><p>vLLM 0.8.5 · Qwen3-0.6B 已实际生成。</p></div></div>
    <div class="step"><span class="num">05</span><div><h3>独立 JSON / schema / 业务校验</h3><p>分别核对语法、结构与答案，保留各层判定。</p></div></div>
  </div></div>
  <div class="info white"><h2>怎么验</h2><div>
    <div class="checks">
      <div class="check"><strong>固定任务与 seed</strong><p>后端对照使用同一任务。</p></div>
      <div class="check"><strong>固定原生 Qwen 模板</strong><p>保留实际使用的模型模板。</p></div>
      <div class="check"><strong>保存 API 入口实际设置</strong><p>记录送进后端的约束设置。</p></div>
      <div class="check"><strong>保存实际响应</strong><p>按原始响应逐层独立校验。</p></div>
    </div>
    <div class="states"><h3>拒绝 / 失败 / 未知仍计入分母</h3>
      <div class="state"><b>拒绝 / 失败</b><span>数组 maxItems → 400；不静默削弱 schema。</span></div>
      <div class="state"><b>未知</b><span>保留证据缺口，不当成功。</span></div>
    </div>
    <p class="input-count"><b>工具只作声明：</b>记录约束，不执行工具。</p>
  </div></div>
</section>

<section class="boundary">
  <div class="takeaway">带走一条</div>
  <strong>格式受约束，答案仍要核对。</strong>
  <div class="limits">
    <p><b>实验范围：</b>CPU 真实 recipe 转换＋小 GPU 后端独立对照。</p>
    <p><b>集成边界：</b>recipe prompt / OutputConstraint 未直接接入 Qwen。</p>
    <p><b>运行边界：</b>两线未端到端集成；未运行 DeepInfer。</p>
  </div>
</section>
<div class="footer">P5·3 · 结构化输出 · 两线独立 / 显式语义映射核对<br>解释卡 · CPU 真实 recipe 转换＋小 GPU 后端独立对照</div>
'''

def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)


if __name__ == '__main__':
    build()
