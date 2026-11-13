"""Phase 4.2 one-page graphic, adapted from the Phase 4.1 HTML template.

Only writes HTML, PNG and temporary browser profiles beside this script.
All statements are supplied scope and experiment status; no benchmark data.
"""
import sys
sys.dont_write_bytecode = True
from render import render

TITLE = '这位乘客还没下车：传输与会话'

CSS = '''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:2080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:64px 76px 52px;display:flex;flex-direction:column}
body>*{flex-shrink:0}
.mono{font-family:Menlo,"SF Mono",monospace}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:24px;line-height:1.3;letter-spacing:.035em}
.eyebrow::before{content:"";width:34px;height:5px;background:#E06C75;border-radius:3px}
h1{font-size:58px;line-height:1.35;font-weight:800;letter-spacing:-.015em;margin-top:20px}
.sub{font-size:27px;line-height:1.5;color:#6f695f;margin-top:10px}
.planes{margin-top:26px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:24px 26px}
.planes h2,.drain h2{font-size:29px;line-height:1.35;font-weight:800}
.paths{display:grid;grid-template-columns:102px minmax(0,1fr);gap:10px 14px;margin-top:16px;align-items:baseline}
.label{font-size:25px;line-height:1.5;font-weight:700;color:#9b4b54}
.path{font-size:27px;line-height:1.5;letter-spacing:-.015em}
.owner{margin-top:18px;border-top:2px solid #eee8dc;padding-top:16px}
.owner h3{font-size:27px;line-height:1.45;font-weight:700}
.owner p{font-size:25px;line-height:1.5;color:#6f695f;margin-top:6px}
.four{display:grid;gap:12px;margin-top:22px}
.info{display:grid;grid-template-columns:128px minmax(0,1fr);gap:20px;border:2px solid;border-radius:20px;padding:20px 26px;align-items:start}
.info h2{font-size:27px;line-height:1.7;font-weight:800;white-space:nowrap}
.info p{font-size:28px;line-height:1.55;letter-spacing:-.015em}
.blue{background:#edf4fa;border-color:#cfdeeb}.blue h2{color:#4b7190}
.orange{background:#fbf1e6;border-color:#f0dcc4}.orange h2{color:#b36c36}
.green{background:#edf5ed;border-color:#d0e1cf}.green h2{color:#4f7a52}
.white{background:#fff;border-color:#e6e0d4}.white h2{color:#6f695f}
.drain{margin-top:24px;border:2px solid #e6e0d4;border-radius:22px;padding:22px 26px;background:#fff}
.sequence{font-size:27px;line-height:1.6;letter-spacing:-.015em;margin-top:16px}
.sequence strong{color:#4f7a52}
.forced{margin-top:16px;padding-top:14px;border-top:2px solid #eee8dc;font-size:25px;line-height:1.5;color:#6f695f}
.forced strong{color:#9b4b54}
.boundary{margin-top:24px;border-top:3px solid #E06C75;padding-top:22px}
.boundary strong{display:block;font-size:31px;line-height:1.5;font-weight:800;white-space:nowrap}
.boundary p{font-size:24px;line-height:1.5;color:#6f695f;margin-top:10px}
.footer{font-size:22px;line-height:1.5;color:#9a9386;margin-top:auto;padding-top:24px}
'''

BODY = '''
<div class="eyebrow">个人进化 · <span class="mono">Phase4 · 2</span></div>
<h1>这位乘客还没下车：<br>传输与会话</h1>
<div class="sub">信令、媒体、会话，各自验证；排空等到播放结束</div>

<section class="planes">
  <h2>信令可达 ≠ 媒体可达</h2>
  <div class="paths">
    <div class="label">信令路径</div><div class="path">HTTP / WS：会话协商与控制</div>
    <div class="label">媒体路径</div><div class="path">ICE 选择的 WebRTC 路径：验证真实 RTP</div>
  </div>
  <div class="owner">
    <h3>会话 owner 与 GPU 推理实例，不是一一绑定</h3>
    <p>职责示意：历史 / 缓冲 / epoch。<br>本实验只验 owner / epoch / 进度；单进程两个逻辑 worker。</p>
  </div>
</section>

<section class="four">
  <div class="info blue"><h2>老做法</h2><p>一条连接一个请求，发完就关。</p></div>
  <div class="info orange"><h2>哪里失效</h2><p>连接可重建，媒体仍在缓冲，<br>历史还留在旧 worker。</p></div>
  <div class="info green"><h2>新方案</h2><p>信令 / 媒体 / 会话分开；<br>sticky owner + 新 epoch 拒绝旧控制；<br>排空同时等任务结束与客户端播放。</p></div>
  <div class="info white"><h2>怎么验</h2><p>看 ICE 候选对与真实 RTP；<br>验重连 offset / 旧 epoch，核对发送与播放两本账；<br>区分正常 drained / 强制 forced 终态。</p></div>
</section>

<section class="drain">
  <h2>排空：任务结束后，还要等乘客下车</h2>
  <div class="sequence">拒绝新会话 → 旧会话继续 → 生产 / 发送结束<br>
  → 客户端缓冲仍播 → 播放 ACK + 会话释放<br>
  → <strong class="mono">drained</strong></div>
  <div class="forced">deadline 到 → <strong class="mono">forced</strong>，保留未播数量。<br>强制结束，不能冒充正常播完。</div>
</section>

<section class="boundary">
  <strong>发完 ≠ 播完；HTTP 200 ≠ 媒体已通</strong>
  <p>session 控制、AudioWorklet 排空分别验证。<br>固定载荷、小样本；未部署 SFU，不作协议快慢排名。</p>
</section>
<div class="footer">exp15 · 固定回放上轮 GPU 音频 · 新增推理 0<br>浏览器渲染非声学测量</div>
'''


def build():
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body>{BODY}</body></html>'
    render('01-一页纸', html, 1080, 2080)


if __name__ == '__main__':
    build()
