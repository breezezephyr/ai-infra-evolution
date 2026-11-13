"""Phase 5.6 explanation card copied from the approved Phase 5.2 template.

Deterministic HTML; user-supplied experiment boundaries, no result counts.
Writes only beside this script.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '进化之路P5·6｜行李不跟车走：KV与分离式服务'

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

<div class="eyebrow">进化之路 · <span class="mono">P5·6</span></div>
<h1>行李不跟车走</h1><div class="sub">KV与分离式服务</div>
<section class="four">
<div class="info blue"><h2>老做法</h2><p>算过的KV随原实例保留，后续请求尽量回到原车。</p></div>
<div class="info orange"><h2>哪里失效</h2><div class="failures">
<div class="failure"><strong>put为0 ≠ 内容已更新</strong><p>已有键可能保留原值，<br>必须核对读回hash。</p></div>
<div class="failure"><strong>空字节 ≠ 确认未命中</strong><p>get会折叠缺失与错误，<br>错误码不能当作真值。</p></div>
<div class="failure"><strong>字节相同 ≠ 状态可用</strong><p>模型、布局、位置变化，<br>都可能使KV不兼容。</p></div>
<div class="failure"><strong>内存还在 ≠ 按键可读</strong><p>master重启后的索引，<br>需要单独验收恢复。</p></div>
</div></div>
<div class="info green"><h2>新方案</h2><div class="flow">
<div class="step"><span class="num">01</span><div><h3>分清索引、搬运、模型语义</h3><p>Store与Transfer Engine接通后，仍需要KV连接层。</p></div></div>
<div class="step"><span class="num">02</span><div><h3>先验真实字节完整性</h3><p>A写、独立B读；长度与SHA256逐一匹配。</p></div></div>
<div class="step"><span class="num">03</span><div><h3>再验身份与失效规则</h3><p>租户 / 模型 / token / 布局 / 位置均需明确。</p></div></div>
<div class="step pending"><span class="num">04</span><div><h3>接入模型后验恢复结果</h3><p>导出、导入、数值与P/D收益，尚待真实模型验证。</p></div></div>
</div></div>
<div class="info white"><h2>怎么验</h2><div>
<div class="checks">
<div class="check"><strong>40个已知对象</strong><p>4种大小 × 10，跨进程读回。</p></div>
<div class="check"><strong>原始返回全部保留</strong><p>重复键 / 删除 / 故障 / 重启。</p></div>
<div class="check"><strong>12个身份教学案例</strong><p>1个不变，11个各改一个字段。</p></div>
<div class="check"><strong>清理也回读</strong><p>逐键查不存在，进程与端口收拢。</p></div>
</div>
<div class="states"><h3>三张凭据，各验一件事</h3>
<div class="state"><b>身份hash</b><span>是否来自同一计算上下文。</span></div>
<div class="state"><b>内容hash</b><span>取回的字节是否完整一致。</span></div>
<div class="state"><b>导入验证</b><span>模型是否能正确恢复并继续计算。</span></div>
</div></div></div></section>
<section class="boundary"><div class="takeaway">带走一条</div><strong>取回完整字节，是复用KV的第一道验收。</strong>
<div class="limits"><p><b>本期实验：</b>真实Store，单机CPU / 配置TCP。</p>
<p><b>身份合约：</b>调用方合成元数据与标志，非模型兼容认证。</p>
<p><b>结论边界：</b>没有GPU、RDMA或真实P/D分离结论。</p></div></section>
<div class="footer">P5·6 · KV与分离式服务<br>解释卡 · 真实字节 / 调用方合约 / 模型接入边界</div>
'''

def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)

if __name__ == '__main__':
    build()
