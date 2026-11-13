"""Render the one-page graphic and copy the original exp14 image unchanged."""
import hashlib
import shutil
import sys
sys.dont_write_bytecode = True
from render import D, render

CSS = '''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:2080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:64px 76px 52px;display:flex;flex-direction:column}
.mono{font-family:Menlo,"SF Mono",monospace}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:24px;line-height:1.3;letter-spacing:.035em}
.eyebrow::before{content:"";width:34px;height:5px;background:#E06C75;border-radius:3px}
h1{font-size:66px;line-height:1.45;font-weight:800;letter-spacing:-.015em;margin-top:24px}
.sub{font-size:30px;line-height:1.5;color:#6f695f;margin-top:14px}
.pipeline{margin-top:32px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:26px}
.chain{display:grid;grid-template-columns:130px 20px minmax(0,1fr) 20px 150px;gap:8px;align-items:center;text-align:center}
.device{font-size:20px;line-height:1.3;color:#8a8378;margin-bottom:10px}
.name{font-size:32px;line-height:1.3;font-weight:700}
.meaning{font-size:23px;line-height:1.4;color:#6f695f;margin-top:6px}
.arrow{font-family:Menlo,monospace;font-size:26px;color:#a39a8d}
.gpu{background:#fcf0f0;border:2px solid #edd1d2;border-radius:16px;padding:14px 12px 16px}
.gpu .device{font-size:20px;color:#9b4b54;margin-bottom:12px;white-space:nowrap}
.models{display:grid;grid-template-columns:1fr 14px 1fr 14px 1fr;gap:3px;align-items:center}
.models .name{font-size:30px}.models .arrow{font-size:20px}
.pipeline-note{margin-top:20px;padding-top:18px;border-top:2px solid #eee8dc;font-size:26px;line-height:1.5}
.pipeline-note strong{color:#9b4b54}
.pipeline-note .muted{color:#6f695f}
.four{display:grid;gap:16px;margin-top:26px}
.info{display:grid;grid-template-columns:128px minmax(0,1fr);gap:20px;border:2px solid;border-radius:20px;padding:24px 26px;align-items:start}
.info h2{font-size:27px;line-height:1.7;font-weight:800;white-space:nowrap}
.info p{font-size:30px;line-height:1.55;letter-spacing:-.015em}
.blue{background:#edf4fa;border-color:#cfdeeb}.blue h2{color:#4b7190}
.orange{background:#fbf1e6;border-color:#f0dcc4}.orange h2{color:#b36c36}
.green{background:#edf5ed;border-color:#d0e1cf}.green h2{color:#4f7a52}
.white{background:#fff;border-color:#e6e0d4}.white h2{color:#6f695f}
.measure{margin-top:28px;border:2px solid #e6e0d4;border-radius:22px;padding:24px 26px;background:#fff}
.measure h2{font-size:27px;line-height:1.3;font-weight:800}
.measure h2 span{font-size:21px;color:#8a8378;font-weight:400;margin-left:12px}
table{width:100%;border-collapse:collapse;margin-top:16px;table-layout:fixed}
th:first-child,td:first-child{width:265px;text-align:left}
th{font-size:24px;font-weight:700;text-align:center;padding:0 0 14px}
th small{display:block;font-size:18px;font-weight:400;color:#8a8378;line-height:1.5;margin-top:3px;white-space:nowrap}
td{font-size:30px;line-height:1.5;padding:9px 0;text-align:center;border-top:2px solid #eee8dc;font-family:Menlo,"SF Mono",monospace}
td:first-child{font-family:"PingFang SC",sans-serif;font-size:24px}
.measure-note{font-size:22px;line-height:1.55;color:#8a8378;margin-top:14px}
.boundary{margin-top:24px;border-top:3px solid #E06C75;padding-top:22px}
.boundary strong{display:block;font-size:31px;line-height:1.5;font-weight:800;white-space:nowrap}
.boundary p{font-size:24px;line-height:1.5;color:#6f695f;margin-top:10px}
.footer{font-size:22px;line-height:1.5;color:#9a9386;margin-top:auto;padding-top:24px}
'''

BODY = '''
<div class="eyebrow">个人进化 · <span class="mono">Phase4 · 1</span></div>
<h1>一句话经过几辆车</h1>
<div class="sub">语音接力 · 从端点到播放，一页看清</div>

<section class="pipeline">
  <div class="chain">
    <div><div class="device mono">CPU</div><div class="name mono">VAD</div><div class="meaning">判断说完</div></div>
    <div class="arrow">→</div>
    <div class="gpu">
      <div class="device">同一张 GPU · 三模型常驻</div>
      <div class="models">
        <div><div class="name mono">ASR</div><div class="meaning">识别</div></div><div class="arrow">→</div>
        <div><div class="name mono">LLM</div><div class="meaning">生成</div></div><div class="arrow">→</div>
        <div><div class="name mono">TTS</div><div class="meaning">合成</div></div>
      </div>
    </div>
    <div class="arrow">→</div>
    <div><div class="device">客户端</div><div class="name">播放</div><div class="meaning">收到 → 出声</div></div>
  </div>
  <div class="pipeline-note"><strong>流水线可重叠：</strong>边生成、边按句合成、边播放。<br>
  <span class="muted">不能把各段独立 p50 相加，预测整轮 p50。</span></div>
</section>

<section class="four">
  <div class="info blue"><h2>老做法</h2><p>等整句、等整答，再开始播。</p></div>
  <div class="info orange"><h2>哪里失效</h2><p>首字出来了，声音还没到。<br>缩短端点等待，又可能抢话。</p></div>
  <div class="info green"><h2>新方案</h2><p>端点、识别、生成、合成、播放，分段观测。<br>生成一句，就交一句给 TTS。</p></div>
  <div class="info white"><h2>怎么验</h2><p>提前端点率 ＋ 有效回合延迟<br>分别看首包、非静音渲染、设备输出估计。</p></div>
</section>

<section class="measure">
  <h2>关键实测<span class="mono">exp14</span></h2>
  <table>
    <thead><tr><th></th><th>A<small>500 ms · 整答</small></th><th>B<small>200 ms · 整答</small></th><th>C<small>200 ms · 分句</small></th></tr></thead>
    <tbody>
      <tr><td>提前端点</td><td>6/36</td><td>9/36</td><td>9/36</td></tr>
      <tr><td>长回答首 PCM · ms</td><td>2436</td><td>2200</td><td>1518</td></tr>
    </tbody>
  </table>
  <div class="measure-note">延迟：参考语音结束 → 客户端收到首 PCM<br>长回答每模式 n=9，数值为 p50；小样本时延对照，非质量结论。<br>有效回合排除提前端点。</div>
</section>

<section class="boundary">
  <strong>首 PCM ≠ 非静音渲染 ≠ 实际听见</strong>
  <p>浏览器接收、非静音渲染、设备输出估计，要分别计时。<br>没有声学回环，设备输出估计不能当作可闻首声。</p>
</section>
<div class="footer">RTX 4060 Laptop · 合成中文输入 · 单会话实验<br>数据：phase4/results/exp14-结论.md</div>
'''


def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)
    source = D.parents[1] / 'phase4' / 'img' / 'exp14.png'
    target = D / '11-exp14.png'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copy2(source, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != before:
        raise RuntimeError('exp14 copy hash mismatch')
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise RuntimeError('exp14 source changed')
    print('11-exp14.png: copied; source/destination SHA-256 match; original unchanged')


if __name__ == '__main__':
    build()
